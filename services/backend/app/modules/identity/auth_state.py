"""验证码与登录限流存储；内存仅供开发，Redis 跨 API 进程原子防重。"""

from __future__ import annotations

import hmac
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import redis

from app.core.errors import DomainError


class AuthState(Protocol):
    """存储摘要与 TTL，不保存手机号、明文验证码或密码。"""

    def issue(self, key: str, digest: str, ttl: int, cooldown: int) -> bool:
        """原子创建验证码与重发冷却。"""
        ...

    def consume(self, key: str, digest: str, max_attempts: int) -> bool:
        """验证码单次消费；错误、过期、重放返回 False。"""
        ...

    def allow(self, key: str, limit: int, window: int) -> bool:
        """固定窗口限制尝试次数。"""
        ...


@dataclass
class Challenge:
    """内存记录；时间为 monotonic 秒，避免系统时钟回拨。"""

    digest: str
    expires: float
    attempts: int = 0


class MemoryAuthState:
    """线程安全开发存储；生产必须选择跨进程共享的 Redis。"""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        """测试可注入时钟，以验证 TTL 而不实际等待。"""
        self.clock = clock
        self.challenges: dict[str, Challenge] = {}
        self.windows: dict[str, tuple[int, float]] = {}
        self.lock = threading.RLock()

    def prune(self) -> None:
        """回收过期记录，避免长时间运行后容量永久耗尽。"""
        current = self.clock()
        self.challenges = {key: value for key, value in self.challenges.items() if value.expires > current}
        self.windows = {key: value for key, value in self.windows.items() if value[1] > current}

    def issue(self, key: str, digest: str, ttl: int, cooldown: int) -> bool:
        """同一锁内创建验证码与冷却。"""
        with self.lock:
            self.prune()
            if not self.allow("code:" + key, 1, cooldown):
                return False
            if len(self.challenges) >= 10000:
                raise DomainError("AUTH_STATE_UNAVAILABLE", "验证服务繁忙，请稍后重试", 503)
            self.challenges[key] = Challenge(digest, self.clock() + ttl)
            return True

    def consume(self, key: str, digest: str, max_attempts: int) -> bool:
        """并发正确请求也只有一个能够消费成功。"""
        with self.lock:
            self.prune()
            record = self.challenges.get(key)
            if record is None:
                return False
            record.attempts += 1
            if record.attempts > max_attempts:
                self.challenges.pop(key, None)
                return False
            valid = hmac.compare_digest(record.digest, digest)
            if valid:
                self.challenges.pop(key, None)
            return valid

    def allow(self, key: str, limit: int, window: int) -> bool:
        """失败请求同样计入窗口。"""
        with self.lock:
            self.prune()
            count, expiry = self.windows.get(key, (0, self.clock() + window))
            self.windows[key] = (count + 1, expiry)
            return count < limit


class RedisAuthState:
    """通过 Lua 原子维护 TTL、尝试次数与单次消费。"""

    ISSUE = """
    if not redis.call('SET', KEYS[2], '1', 'NX', 'EX', ARGV[3]) then return 0 end
    redis.call('HSET', KEYS[1], 'digest', ARGV[1], 'attempts', 0)
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 1
    """
    CONSUME = """
    local digest = redis.call('HGET', KEYS[1], 'digest')
    if not digest then return 0 end
    local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
    if attempts > tonumber(ARGV[2]) then redis.call('DEL', KEYS[1]); return 0 end
    if digest ~= ARGV[1] then return 0 end
    redis.call('DEL', KEYS[1])
    return 1
    """
    ALLOW = """
    local count = redis.call('INCR', KEYS[1])
    if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
    if count <= tonumber(ARGV[1]) then return 1 else return 0 end
    """

    def __init__(self, url: str, namespace: str = "yingxu:auth"):
        """超时有界；Redis 故障不能静默回退到各进程独立内存。"""
        self.client = redis.Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
        )
        self.namespace = namespace

    def evaluate(self, script: str, keys: list[str], *args: str | int) -> bool:
        """失败关闭入口，公开错误不包含连接 URL。"""
        try:
            return bool(self.client.eval(script, len(keys), *keys, *args))
        except redis.RedisError as exc:
            raise DomainError("AUTH_STATE_UNAVAILABLE", "验证服务暂不可用，请稍后重试", 503) from exc

    def issue(self, key: str, digest: str, ttl: int, cooldown: int) -> bool:
        """同 hash tag 兼容 Redis Cluster 的跨键脚本。"""
        tag = f"{self.namespace}:{{{key}}}"
        return self.evaluate(self.ISSUE, [tag + ":challenge", tag + ":cooldown"], digest, ttl, cooldown)

    def consume(self, key: str, digest: str, max_attempts: int) -> bool:
        """成功后只移除验证码，保留重发冷却。"""
        return self.evaluate(self.CONSUME, [f"{self.namespace}:{{{key}}}:challenge"], digest, max_attempts)

    def allow(self, key: str, limit: int, window: int) -> bool:
        """限流计数不随业务数据库回滚。"""
        return self.evaluate(self.ALLOW, [f"{self.namespace}:limit:{key}"], limit, window)

    def close(self) -> None:
        """关闭连接池。"""
        self.client.close()

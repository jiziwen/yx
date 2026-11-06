"""真实 Redis 验收：跨 API 进程验证码、并发消费、限流和过期；不使用用户 Redis。"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.errors import DomainError
from app.main import create_app
from app.modules.identity.auth_state import RedisAuthState

pytestmark = pytest.mark.skipif(
    not os.environ.get("YINGXU_TEST_REDIS_URL"), reason="由 pnpm test:redis 在隔离容器中执行"
)


@pytest.fixture
def stores():
    """两个独立存储实例共享本次测试的随机命名空间，结束只删自身测试键。"""
    namespace = "yingxu:test:" + uuid4().hex
    url = os.environ["YINGXU_TEST_REDIS_URL"]
    first, second = RedisAuthState(url, namespace), RedisAuthState(url, namespace)
    yield first, second
    keys = list(first.client.scan_iter(match=namespace + "*"))
    if keys:
        first.client.delete(*keys)
    first.close()
    second.close()


def test_code_issued_by_one_api_consumed_by_another(app, stores):
    """部署多个 API 进程不会导致验证码只在发送它的进程里有效。"""
    first, second = stores
    app.state.auth_state = first
    peer = create_app(app.state.settings, engine=app.state.engine)
    peer.state.auth_state = second
    with TestClient(app) as a, TestClient(peer) as b:
        code = a.post("/api/v1/web/auth/code", json={"phone": "13900008881"})
        assert code.status_code == 200
        body = {"phone": "13900008881", "code": code.json()["debug_code"]}
        assert b.post("/api/v1/web/auth/login", json=body).status_code == 200
        assert a.post("/api/v1/web/auth/login", json=body).status_code == 400
        assert b.post("/api/v1/web/auth/code", json={"phone": body["phone"]}).status_code == 429


def test_concurrent_consumption_and_shared_attempt_limit(stores):
    """跨连接同时消费正确验证码只能成功一次；两边共享错误次数和登录限流。"""
    first, second = stores
    assert first.issue("subject", "digest", 300, 60)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(
            pool.map(lambda i: (first if i % 2 else second).consume("subject", "digest", 5), range(8))
        )
    assert sum(outcomes) == 1
    assert first.issue("wrong", "correct", 300, 60)
    for index in range(5):
        assert not (first if index % 2 else second).consume("wrong", "incorrect", 5)
    assert not second.consume("wrong", "correct", 5)
    assert [first.allow("ip", 2, 300), second.allow("ip", 2, 300), first.allow("ip", 2, 300)] == [
        True,
        True,
        False,
    ]


def test_expired_challenge_and_cooldown_are_reclaimed(stores):
    """真实 Redis TTL 到期后不可消费，冷却到期允许重新创建。"""
    first, second = stores
    assert first.issue("short", "digest", 1, 1)
    assert first.client.ttl(f"{first.namespace}:{{short}}:challenge") <= 1
    deadline = time.monotonic() + 3
    while first.client.exists(f"{first.namespace}:{{short}}:challenge") and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not second.consume("short", "digest", 5)
    assert second.issue("short", "new", 1, 1)


def test_disconnected_redis_fails_closed():
    """依赖断开时返回稳定 503，不退回内存或暴露连接详情。"""
    state = RedisAuthState("redis://127.0.0.1:1/0")
    with pytest.raises(DomainError) as error:
        state.allow("key", 1, 30)
    assert error.value.status == 503 and "redis://" not in error.value.message
    state.close()

"""可插拔模型调用记录；网关统一计次，适配器补充实际 HTTP 入参与出参。"""

import inspect
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields, is_dataclass
from hashlib import sha256
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select

from app.core.db import now, uid
from app.modules.operations.models import ModelCall

CALL_SCOPE = ContextVar("model_call_scope", default={})
ACTIVE_CALL = ContextVar("model_call", default=None)
METHODS = {"draft", "complete", "stream_complete", "generate", "submit", "lookup", "embed"}
SECRET_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "access_token",
    "cookie",
    "set-cookie",
}
MAX_PAYLOAD = 256_000


@contextmanager
def call_scope(context):
    """将工具中的嵌套模型调用关联到服务端确定的用户和项目。"""
    token = CALL_SCOPE.set(context)
    try:
        yield
    finally:
        CALL_SCOPE.reset(token)


def blob(value):
    """二进制不复制到日志，保留可比对的字节数及摘要。"""
    return {"omitted": "binary", "bytes": len(value), "sha256": sha256(value).hexdigest()}


def sanitize(value, secrets=(), depth=0):
    """在落库前移除凭证、签名链接和图片正文，并显式标记裁剪。"""
    if depth > 16:
        return {"omitted": "depth_limit"}
    if is_dataclass(value):
        value = {item.name: getattr(value, item.name) for item in fields(value)}
    if isinstance(value, bytes):
        return blob(value)
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:200]:
            name = str(key)
            if name.lower() in SECRET_KEYS or name.lower().endswith(("_api_key", "_secret")):
                result[name] = "[REDACTED]"
            elif name in {"b64_json", "base64"} and isinstance(item, str):
                result[name] = {
                    "omitted": "base64",
                    "characters": len(item),
                    "sha256": sha256(item.encode()).hexdigest(),
                }
            elif name in {"reasoning_content", "reasoning", "thinking"}:
                result[name] = "[OMITTED]"
            else:
                # 302 将结果 JSON 放在 data 字符串时也要去除图片正文。
                if name == "data" and isinstance(item, str) and item.lstrip().startswith(("{", "[")):
                    try:
                        item = json.loads(item)
                    except ValueError:
                        pass
                result[name] = sanitize(item, secrets, depth + 1)
        if len(value) > 200:
            result["_truncated_keys"] = len(value) - 200
        return result
    if isinstance(value, (list, tuple)):
        result = [sanitize(item, secrets, depth + 1) for item in value[:200]]
        if len(value) > 200:
            result.append({"omitted_items": len(value) - 200})
        return result
    if isinstance(value, str):
        if value.startswith("data:"):
            return {
                "omitted": "data_url",
                "characters": len(value),
                "sha256": sha256(value.encode()).hexdigest(),
            }
        value = re.sub(r"data:[^,\s]+;base64,[A-Za-z0-9+/=]+", "[DATA URL OMITTED]", value)
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)

        def safe_url(match):
            """不保存可直接获取私有文件的 URL 查询凭证。"""
            try:
                parsed = urlsplit(match.group())
                return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
            except ValueError:
                return "[URL OMITTED]"

        value = re.sub(r"https?://[^\s\"<>]+", safe_url, value)
        return value if len(value) <= 64000 else value[:64000] + "\n[TRUNCATED]"
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return {"type": type(value).__name__}


def bounded(value, secrets=()):
    """总载荷上限固定；越界时保留可读预览及显式标记。"""
    result = sanitize(value, secrets)
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > MAX_PAYLOAD:
        return {
            "truncated": True,
            "preview": encoded.encode()[: MAX_PAYLOAD // 3].decode("utf-8", errors="ignore"),
        }
    return result


def wire_request(method, endpoint, **kwargs):
    """适配器在发送前补充实际参数，绝不接收或存储认证请求头。"""
    active = ACTIVE_CALL.get()
    if active is not None:
        active["request"] = {"method": method, "endpoint": endpoint, **kwargs}
        body = kwargs.get("json") or kwargs.get("data")
        if isinstance(body, dict) and isinstance(body.get("model"), str):
            active["model"] = body["model"][:200]
        # 发出前独立保存实际参数，进程中断时也保留提示词和实际模型。
        active["persist_request"]()


def wire_secret(value):
    """仅在本次调用内用于脱敏，不进入日志。"""
    active = ACTIVE_CALL.get()
    if active is not None and value:
        active["secrets"].append(value)


def wire_response(body, status):
    """记录已收到的原始业务响应；HTTP 错误正文仅保留脱敏后的有界内容。"""
    active = ACTIVE_CALL.get()
    if active is not None:
        active["response"], active["http_status"] = body, status


def response_body(response):
    """非 JSON 响应也可排查，禁止让观测错误影响适配器原有行为。"""
    try:
        return response.json()
    except ValueError:
        return {"text": response.text[:64000]}


def visible_payload(db, row):
    """撤销/删除后即刻屏蔽正文，迟到的模型回包不能复活旧隐私代次。"""
    from app.modules.identity.models import User
    from app.modules.projects.models import Project

    if row.owner_user_id:
        user = db.get(User, row.owner_user_id)
        if not user or user.status != "active":
            return False
    if row.project_id:
        project = db.get(Project, row.project_id)
        if not project or project.lifecycle != "active" or project.privacy_epoch != row.privacy_epoch:
            return False
    return True


def scrub_calls(db, *, project_id=None, owner_user_id=None):
    """沿用项目/账户删除屏障，保留调用事实并清空请求响应正文。"""
    query = select(ModelCall)
    query = (
        query.where(ModelCall.project_id == project_id)
        if project_id
        else query.where(ModelCall.owner_user_id == owner_user_id)
    )
    for row in db.scalars(query):
        if project_id and visible_payload(db, row):
            continue
        row.request_json = row.response_json = {"scrubbed": True}


class CallRecorder:
    """独立短事务记录提交前意图和最终返回，业务回滚不会删除调用证据。"""

    def __init__(self, sessions):
        """不保存密钥；每次调用从当前插件读取用于落库脱敏。"""
        self.sessions = sessions

    def wrap(self, provider, provider_id, definition, context=None):
        """仅代理插件实际具有的方法，保持同步/异步/流式能力协议不变。"""
        recorder = self
        context = context or CALL_SCOPE.get()

        class Observed:
            """非调用属性透明转发，未声明的方法不能制造新能力。"""

            def __getattr__(self, name):
                return getattr(provider, name)

            def __setattr__(self, name, value):
                setattr(provider, name, value)

            def __delattr__(self, name):
                delattr(provider, name)

        def method(name, function):
            """生成独立方法，避免 draft 内部 complete 被重复计次。"""

            def invoke(self, *args, **kwargs):
                return recorder.invoke(
                    provider, provider_id, definition, context or {}, name, function, args, kwargs
                )

            return invoke

        wrapped = type(
            "ObservedProvider",
            (Observed,),
            {
                name: method(name, getattr(provider, name))
                for name in METHODS
                if callable(getattr(provider, name, None))
            },
        )
        return wrapped()

    def invoke(self, provider, provider_id, definition, context, method, function, args, kwargs):
        """每次显式模型操作一条记录；绝不为日志执行重试或第二次付费调用。"""
        active = ACTIVE_CALL.get()
        if active is not None and active["provider"] == id(provider):
            return function(*args, **kwargs)
        arguments = dict(inspect.signature(function).bind(*args, **kwargs).arguments)
        arguments.pop("on_content", None)
        options = definition.get("options", {})
        model = (
            options.get("model")
            or getattr(provider, "model", None)
            or getattr(provider, "spec", {}).get("model")
        )
        if not model and options.get("models"):
            request = arguments.get("request")
            model = options["models"].get(getattr(request, "operation", "")) or ", ".join(
                dict.fromkeys(options["models"].values())
            )
        row = ModelCall(
            id=uid(),
            provider_id=provider_id,
            kind=definition["kind"],
            model=str(model or provider_id)[:200],
            operation=method,
            status="running",
            development_sample=definition.get("development_only", False),
            project_id=context.get("project_id"),
            owner_user_id=context.get("owner_user_id"),
            run_id=context.get("run_id"),
            job_id=context.get("job_id"),
            privacy_epoch=context.get("privacy_epoch"),
            request_json={},
            response_json=None,
        )
        secrets = (getattr(provider, "key", None),)
        with self.sessions() as db:
            if visible_payload(db, row):
                row.request_json = bounded(arguments, secrets)
            else:
                row.request_json = {"scrubbed": True}
            db.add(row)
            db.commit()

        def persist_request():
            """观测失败不能阻止原请求，也不能触发重发。"""
            try:
                with self.sessions() as db:
                    stored = db.get(ModelCall, row.id)
                    if visible_payload(db, stored):
                        stored.request_json = bounded(state["request"], state["secrets"])
                    else:
                        stored.request_json = {"scrubbed": True}
                    stored.model = state["model"]
                    db.commit()
            except Exception:
                logging.error("model_call_request_failed call_id=%s", row.id)

        state = {
            "provider": id(provider),
            "persist_request": persist_request,
            "model": row.model,
            "request": arguments,
            "response": None,
            "http_status": None,
            "secrets": list(secrets),
        }
        token = ACTIVE_CALL.set(state)
        started, result, failure = monotonic(), None, None
        try:
            result = function(*args, **kwargs)
            return result
        except BaseException as exc:
            failure = exc
            raise
        finally:
            ACTIVE_CALL.reset(token)
            try:
                with self.sessions() as db:
                    stored = db.get(ModelCall, row.id)
                    stored.finished_at, stored.latency_ms = now(), int((monotonic() - started) * 1000)
                    stored.status = "succeeded" if failure is None else "failed"
                    stored.error_code = getattr(failure, "code", "PROVIDER_UNAVAILABLE") if failure else None
                    stored.result_unknown = bool(getattr(failure, "unknown", False))
                    stored.http_status = state["http_status"]
                    stored.model = state["model"]
                    if visible_payload(db, stored):
                        stored.request_json = bounded(state["request"], state["secrets"])
                        stored.response_json = bounded(
                            state["response"] if state["response"] is not None else result, state["secrets"]
                        )
                    else:
                        stored.request_json = stored.response_json = {"scrubbed": True}
                    db.commit()
            except Exception:
                # 远端结果已产生；日志落库失败不能改成失败并触发重复付费。
                logging.error("model_call_finish_failed call_id=%s", row.id)

"""FastAPI 装配入口；按可信配置安装模块，启动不自动建表或接入真实模型。"""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException

import app.core.models  # noqa: F401 — 迁移和运行时共享模型注册，不依赖模块开关。
from app.core.config import Settings
from app.core.contracts import ERROR_RESPONSES, HealthView, ReadyView
from app.core.db import make_engine
from app.core.errors import DomainError
from app.core.plugins import install_modules
from app.core.readiness import check_migrations
from app.integrations.live import bind_live_gateway
from app.integrations.registry import Gateway
from app.modules.catalog.configuration import load_catalog
from app.modules.identity.auth_state import MemoryAuthState, RedisAuthState
from app.modules.identity.credentials import hash_password


def create_app(settings: Settings | None = None, engine=None, *, contract_only: bool = False) -> FastAPI:
    """创建可测试的应用实例；部署配置错误必须尽早失败。"""
    settings = settings or Settings()
    if not contract_only:
        settings.validate_runtime()
        from evals.m25_runtime import check as check_experiment

        check_experiment(settings)
    config = settings.application_config()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """仅释放本应用拥有的连接池，不关闭测试或调用者传入的共享 engine。"""
        try:
            yield
        finally:
            state = getattr(application.state, "auth_state", None)
            if isinstance(state, RedisAuthState):
                state.close()
            if not contract_only and engine is None:
                application.state.engine.dispose()

    application = FastAPI(
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
        title="映序 API",
        version="0.1.0",
        description="M0 + M1 开发闭环；接口前缀隔离用户与管理身份",
    )
    application.state.settings = settings
    application.state.config = config
    application.state.catalog = load_catalog(
        settings.catalog_file, allow_development=settings.app_env != "production"
    )
    if not contract_only:
        application.state.gateway = Gateway(config, settings)
        application.state.engine = engine or make_engine(settings.database_url)
        application.state.sessions = sessionmaker(application.state.engine, expire_on_commit=False)
        from app.integrations.call_logging import CallRecorder

        application.state.model_calls = CallRecorder(application.state.sessions)
        application.state.gateway.recorder = application.state.model_calls
        bind_live_gateway(application)
        application.state.auth_state = (
            RedisAuthState(settings.redis_url)
            if settings.auth_state_backend == "redis"
            else MemoryAuthState()
        )
        application.state.dummy_admin_hash = hash_password(str(uuid4()))
    application.state.modules = install_modules(application, config["modules"])
    from app.modules.agents.tools import ReadToolRegistry

    application.state.agent_tools = ReadToolRegistry(config["agent"]["tools"])
    installed = {module.id for module in application.state.modules}
    for flag, dependencies in {
        "trial_enabled": {"commerce"},
        "chat_enabled": {"conversations", "agents"},
        "support_enabled": {"conversations", "agents"},
        "gifts_enabled": {"gifts"},
        "payments_enabled": {"payments"},
    }.items():
        if config["features"].get(flag) and not dependencies.issubset(installed):
            raise ValueError(f"功能 {flag} 缺少已启用模块：{sorted(dependencies - installed)}")
    if settings.app_env == "production" and not contract_only and config["features"].get("chat_enabled"):
        from app.modules.agents.releases import release_snapshot

        release_snapshot(application, application.state.gateway.snapshot("llm"))
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        """关联请求 ID 并拒绝不可信跨站 Cookie 写操作。"""
        request.state.request_id = str(uuid4())
        if settings.m25_run_id:
            try:
                check_experiment(settings)
            except DomainError:
                return JSONResponse(
                    {"error": {"code": "EXPERIMENT_PAUSED", "message": "隔离实验已过期或暂停"}},
                    status_code=409,
                )
        origin = request.headers.get("origin")
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin not in settings.allowed_origins
        ):
            return JSONResponse(
                {
                    "error": {
                        "code": "ORIGIN_DENIED",
                        "message": "请求来源不被允许",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=403,
                headers={"X-Request-ID": request.state.request_id, "Cache-Control": "no-store"},
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        """返回可操作的业务错误，不输出异常堆栈或上游正文。"""
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "request_id": request.state.request_id}},
            status_code=exc.status,
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        """校验错误去掉原始输入，避免手机号和照片信息进入响应。"""
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求字段不完整或格式不正确",
                    "request_id": request.state.request_id,
                    "details": [{"loc": error["loc"], "type": error["type"]} for error in exc.errors()],
                }
            },
            status_code=422,
        )

    @application.exception_handler(IntegrityError)
    async def conflict(request: Request, exc: IntegrityError):
        """并发唯一性冲突统一返回 409，事务由依赖回滚。"""
        return JSONResponse(
            {
                "error": {
                    "code": "CONCURRENT_CONFLICT",
                    "message": "操作发生并发冲突，请刷新后重试",
                    "request_id": request.state.request_id,
                }
            },
            status_code=409,
        )

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        """兜底错误保持契约，日志只包含类型与请求关联 ID，不记录敏感正文。"""
        request_id = getattr(request.state, "request_id", "unknown")
        logging.error("request_failed kind=%s request_id=%s", type(exc).__name__, request_id)
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务暂时遇到问题，请稍后重试",
                    "request_id": request_id,
                }
            },
            status_code=500,
            headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        """框架级 404/405 也使用统一信封，避免客户端另猜一种响应结构。"""
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "接口不存在或资源不可访问" if exc.status_code == 404 else "请求方法或格式不被允许"
        return JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request.state.request_id}},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @application.get("/health", tags=["health"], response_model=HealthView)
    def health():
        """轻量进程健康；不伪装数据库或队列就绪。"""
        return {"status": "ok", "version": "0.1.0"}

    @application.get("/ready", tags=["health"], response_model=ReadyView)
    def ready(request: Request):
        """检查精确迁移头；旧库、未知版本与不可达数据库均返回 503。"""
        try:
            revision = check_migrations(application.state.engine)
            return {"status": "ready", "migration": revision}
        except Exception:
            return JSONResponse(
                {
                    "error": {
                        "code": "DATABASE_NOT_READY",
                        "message": "数据库不可用或迁移版本不兼容",
                        "request_id": request.state.request_id,
                    }
                },
                status_code=503,
            )

    return application

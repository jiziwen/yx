"""M0 工程验收：受控身份、会话、统一契约、迁移就绪与原子认证状态。"""

from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_creative_flow import create_project, login

from app.cli import main as cli
from app.core.config import Settings
from app.core.errors import DomainError
from app.main import create_app
from app.modules.identity.auth_state import MemoryAuthState
from app.modules.identity.credentials import hash_password, provision_admin, verify_password
from app.modules.identity.models import AdminCredential, User


def test_password_salt_and_corrupt_digest():
    """相同密码的随机盐不同，错误密码、未知算法与损坏凭证均拒绝。"""
    password = "local-test-only-passphrase"
    first, second = hash_password(password), hash_password(password)
    assert first != second and password not in first
    assert verify_password(password, first)
    assert not verify_password("wrong-password", first)
    assert not verify_password(password, "invalid")
    assert not verify_password(password, first.replace("pbkdf2_sha256", "unknown"))


def test_database_admin_bootstrap_and_no_credential_overwrite(app, monkeypatch):
    """数据库模式下环境变量密码不能登录；CLI 明确开通，重试不覆盖密码。"""
    app.state.settings.admin_auth_mode = "database"
    password = "isolated-test-only-passphrase"
    monkeypatch.setattr("sys.stdin", StringIO(password + "\n"))
    assert cli(["create-admin", "--username", "ops", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", StringIO("another-password-123\n"))
    assert cli(["create-admin", "--username", "ops", "--password-stdin"]) == 2
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/admin/auth/login",
                json={"username": "admin", "password": app.state.settings.admin_password},
            ).status_code
            == 401
        )
        response = client.post("/api/v1/admin/auth/login", json={"username": "ops", "password": password})
        assert response.status_code == 200
        assert client.get("/api/v1/admin/catalog").status_code == 200
    with app.state.sessions() as db:
        credential = db.scalar(select(AdminCredential).where(AdminCredential.username == "ops"))
        assert verify_password(password, credential.password_hash)
        assert db.get(User, credential.user_id).role == "admin"


def test_bootstrap_rejects_weak_password(app):
    """受控入口也不能开通弱密码。"""
    with app.state.sessions() as db, pytest.raises(DomainError):
        provision_admin(db, "ops", "short", "测试管理员")


def test_cookie_audience_logout_and_blocked_account(app, client):
    """会话不可跨入口复用，退出与账户封禁使已签发 Cookie 失效。"""
    user = login(client)
    cookie = client.cookies.get("yx_web")
    client.cookies.set("yx_admin", cookie, path="/api/v1/admin")
    assert client.get("/api/v1/admin/me").status_code == 401
    assert client.post("/api/v1/web/auth/logout").status_code == 200
    client.cookies.set("yx_web", cookie, path="/api/v1/web")
    assert client.get("/api/v1/web/me").status_code == 401
    with app.state.sessions() as db:
        db.get(User, user["id"]).status = "blocked"
        db.commit()
    assert client.get("/api/v1/web/me").status_code == 401


def test_admin_ttl_and_cookie_flags(app, client, monkeypatch):
    """管理员使用独立的短 TTL，Cookie 不向 JS 暴露。"""
    app.state.settings.admin_session_ttl = 60
    response = client.post(
        "/api/v1/admin/auth/login", json={"username": "admin", "password": app.state.settings.admin_password}
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/v1/admin" in cookie
    assert "max-age=60" in cookie
    from itsdangerous import TimestampSigner

    original = TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) + 61)
    assert client.get("/api/v1/admin/me").status_code == 401


def test_memory_challenge_limits_expiry_and_concurrent_consume():
    """验证码限次、过期、重放与并发消费都独立于业务数据库。"""
    current = [0.0]
    state = MemoryAuthState(clock=lambda: current[0])
    assert state.issue("subject", "digest", 300, 60)
    assert not state.issue("subject", "replacement", 300, 60)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: state.consume("subject", "digest", 5), range(8)))
    assert sum(results) == 1
    current[0] = 61
    assert state.issue("subject", "new-digest", 300, 60)
    for _ in range(5):
        assert not state.consume("subject", "wrong", 5)
    assert not state.consume("subject", "new-digest", 5)
    current[0] = 400
    assert state.issue("subject", "expired", 300, 60)
    current[0] = 701
    assert not state.consume("subject", "expired", 5)
    assert not state.challenges


def test_framework_validation_errors_share_request_id(client):
    """未登录、参数错误、404、405 与来源拒绝使用同一错误信封且不回显输入。"""
    cases = [
        client.get("/api/v1/web/me"),
        client.post("/api/v1/web/auth/code", json={"phone": "private-marker"}),
        client.get("/api/v1/web/missing"),
        client.put("/api/v1/web/me"),
        client.post("/api/v1/web/auth/logout", headers={"Origin": "https://not-allowed.example"}),
    ]
    for response in cases:
        assert response.status_code in {401, 422, 404, 405, 403}
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
        assert "private-marker" not in response.text


def test_internal_errors_are_redacted_and_correlated(app, caplog):
    """未知异常也保留关联 ID，响应和日志不包含异常正文。"""

    @app.get("/test/internal-error")
    def fail():
        """测试专用故障注入。"""
        raise RuntimeError("sensitive-upstream-marker")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test/internal-error")
    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "sensitive-upstream-marker" not in response.text + caplog.text


def test_readiness_checks_precise_migration_head(app, client):
    """M0 新迁移尚未执行时返回 503，升级后恢复，不对旧库报告就绪。"""
    assert client.get("/ready").status_code == 200
    command.downgrade(Config("alembic.ini"), "cea21ffc2ac6")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert client.get("/health").status_code == 200
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    assert client.get("/ready").status_code == 200


def test_datetime_contract_is_utc(client):
    """SQLite 和 PostgreSQL 都向前端提供带 UTC 标识的日期。"""
    login(client)
    project = create_project(client)
    assert project["created_at"].endswith("Z")


def test_production_requires_database_identity_and_shared_state():
    """开发密码与进程内认证状态不能进入生产。"""
    with pytest.raises(ValueError, match="数据库管理凭证"):
        create_app(
            Settings(
                app_env="production",
                database_url="postgresql+psycopg://unused",
                dev_login_enabled=False,
                session_secret="x" * 48,
            )
        )


def test_openapi_export_has_no_runtime_side_effects(monkeypatch):
    """离线契约不创建连接、私有目录或初始化模型，部署密钥不影响生成。"""

    def forbidden(*args, **kwargs):
        """任何运行时初始化都使导出测试失败。"""
        raise AssertionError("runtime initialization during contract export")

    monkeypatch.setattr("app.main.make_engine", forbidden)
    monkeypatch.setattr("app.main.Gateway", forbidden)
    monkeypatch.setattr("app.main.hash_password", forbidden)
    app = create_app(Settings.model_construct(), contract_only=True)
    schema = app.openapi()
    assert "ErrorEnvelope" in schema["components"]["schemas"]
    assert "InventoryView" in schema["components"]["schemas"]
    assert not hasattr(app.state, "engine")


def test_admin_password_whitespace_is_not_silently_modified(app):
    """密码和普通文案的 trim 规则不同，开通与登录必须使用相同字节。"""
    password = "  local-test-passphrase  "
    app.state.settings.admin_auth_mode = "database"
    with app.state.sessions() as db:
        provision_admin(db, "spaced", password, "测试管理员")
        db.commit()
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/admin/auth/login", json={"username": "spaced", "password": password}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/admin/auth/login", json={"username": "spaced", "password": password.strip()}
            ).status_code
            == 401
        )

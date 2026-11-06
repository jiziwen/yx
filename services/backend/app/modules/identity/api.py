"""独立用户/管理登录入口；假短信只在显式开发模式可用。"""

import hmac
import secrets
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import Field, StringConstraints
from sqlalchemy import select

from app.core.contracts import CodeView, OkView
from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, StaffDep, UserDep, set_cookie
from app.core.views import UserView

from .credentials import provision_admin, verify_password
from .models import AdminCredential, User

router = APIRouter(tags=["identity"])


class CodeInput(Input):
    """手机号仅用于验证码和服务端 HMAC，不写日志或本地浏览器存储。"""

    phone: str = Field(pattern=r"^1[3-9]\d{9}$", description="中国大陆开发登录手机号")


class LoginInput(CodeInput):
    """验证码有 TTL、次数限制且只消费一次。"""

    code: str = Field(min_length=6, max_length=6)


class AdminLogin(Input):
    """管理凭证由部署环境设置，不接受 role 字段。"""

    username: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=128)


def phone_hash(request: Request, phone: str) -> str:
    """带服务器秘密的查找 HMAC，避免公开哈希被枚举。"""
    return hmac.new(request.app.state.settings.session_secret.encode(), phone.encode(), sha256).hexdigest()


@router.post("/api/v1/web/auth/code", response_model=CodeView)
def send_code(body: CodeInput, request: Request) -> dict:
    """仅开发假短信；真实短信与 Redis 验证码适配属于 M1 接入项。"""
    if not request.app.state.settings.dev_login_enabled:
        raise DomainError("SMS_UNAVAILABLE", "短信服务尚未配置", 503)
    key = phone_hash(request, body.phone)
    code = f"{secrets.randbelow(1000000):06d}"
    digest = phone_hash(request, key + ":" + code)
    if not request.app.state.auth_state.issue(key, digest, ttl=300, cooldown=60):
        raise DomainError("RATE_LIMITED", "请稍后再获取验证码", 429)
    return {"development_only": True, "debug_code": code, "expires_in": 300}


@router.post("/api/v1/web/auth/login", response_model=UserView)
def login(body: LoginInput, request: Request, response: Response, db: DB):
    """消费一次验证码后建立普通用户，管理角色没有注册入口。"""
    if not request.app.state.settings.dev_login_enabled:
        raise DomainError("SMS_UNAVAILABLE", "短信服务尚未配置", 503)
    key = phone_hash(request, body.phone)
    digest = phone_hash(request, key + ":" + body.code)
    if not request.app.state.auth_state.consume(key, digest, max_attempts=5):
        raise DomainError("INVALID_CODE", "验证码无效或已过期", 400)
    user = db.scalar(select(User).where(User.login_hash == key))
    if user is None:
        user = User(login_hash=key)
        db.add(user)
        db.flush()
    if user.status != "active":
        raise DomainError("ACCOUNT_UNAVAILABLE", "账户暂不可用", 403)
    db.commit()
    set_cookie(request, response, user, "web")
    return user


@router.get("/api/v1/web/me", response_model=UserView)
def me(user: UserDep):
    """当前用户身份，不返回手机号或 Cookie。"""
    return user


@router.post("/api/v1/web/auth/logout", response_model=OkView)
def logout(request: Request, response: Response, user: UserDep, db: DB):
    """撤销此账户的现有会话；浏览器 Cookie 同步清除。"""
    user.session_version += 1
    db.commit()
    response.delete_cookie("yx_web", path="/api/v1/web")
    return {"ok": True}


@router.post("/api/v1/admin/auth/login", response_model=UserView)
def admin_login(body: AdminLogin, request: Request, response: Response, db: DB):
    """本地管理员首次登录时受控开通；生产不自动创建管理员。"""
    settings = request.app.state.settings
    address = request.client.host if request.client else "unknown"
    rate_key = phone_hash(request, "admin:" + address + ":" + body.username)
    if not request.app.state.auth_state.allow(rate_key, limit=5, window=300):
        raise DomainError("RATE_LIMITED", "请五分钟后重试", 429)
    credential = db.scalar(select(AdminCredential).where(AdminCredential.username == body.username))
    # 兼容已有开发库；只有显式开发模式才允许首次初始化，生产从不自动创建账户。
    if (
        credential is None
        and settings.admin_auth_mode == "development"
        and settings.app_env != "production"
        and body.username == "admin"
        and hmac.compare_digest(body.password, settings.admin_password)
    ):
        provision_admin(db, "admin", settings.admin_password, "映序管理员")
        credential = db.scalar(select(AdminCredential).where(AdminCredential.username == "admin"))
    encoded = credential.password_hash if credential else request.app.state.dummy_admin_hash
    valid = verify_password(body.password, encoded)
    if credential is None or not valid:
        raise DomainError("INVALID_CREDENTIALS", "管理账号或密码错误", 401)
    user = db.get(User, credential.user_id)
    if user is None or user.role not in {"admin", "staff"} or user.status != "active":
        raise DomainError("ACCOUNT_UNAVAILABLE", "管理身份暂不可用", 403)
    db.commit()
    set_cookie(request, response, user, "admin")
    return user


@router.get("/api/v1/admin/me", response_model=UserView)
def admin_me(user: StaffDep):
    """管理入口只接受独立管理 Cookie。"""
    return user


@router.post("/api/v1/admin/auth/logout", response_model=OkView)
def admin_logout(response: Response, user: StaffDep, db: DB):
    """退出管理会话并使旧 Cookie 失效。"""
    user.session_version += 1
    db.commit()
    response.delete_cookie("yx_admin", path="/api/v1/admin")
    return {"ok": True}

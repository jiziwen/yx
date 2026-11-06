"""独立用户/管理 Cookie 会话；每次请求复核账户状态和会话撤销版本。"""

from typing import Annotated

from fastapi import Depends, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.identity.models import User


def session(request: Request):
    """为单个请求提供数据库事务，关闭连接时回滚未提交更改。"""
    with request.app.state.sessions() as db:
        if request.method not in {"GET", "HEAD", "OPTIONS"} and db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield db


DB = Annotated[Session, Depends(session)]


def current_user(request: Request, db: DB) -> User:
    """用户资源只接受 web 会话；管理 Cookie 不可替换用户入口。"""
    return authenticate(request, db, "web")


def current_admin(request: Request, db: DB) -> User:
    """管理角色来自服务端账户，客户端不可声明角色。"""
    user = authenticate(request, db, "admin")
    if user.role != "admin":
        raise DomainError("PERMISSION_DENIED", "需要管理员权限", 403)
    return user


def current_staff(request: Request, db: DB) -> User:
    """客服员工使用独立管理Cookie；发布/模型/权益仍要求管理员。"""
    user = authenticate(request, db, "admin")
    if user.role not in {"staff", "admin"}:
        raise DomainError("PERMISSION_DENIED", "需要客服员工权限", 403)
    return user


StaffDep = Annotated[User, Depends(current_staff)]


UserDep = Annotated[User, Depends(current_user)]
AdminDep = Annotated[User, Depends(current_admin)]


def serializer(request: Request, audience: str) -> URLSafeTimedSerializer:
    """按入口隔离签名空间，限制 Cookie 相互替换。"""
    return URLSafeTimedSerializer(request.app.state.settings.session_secret, salt=f"yingxu-{audience}")


def authenticate(request: Request, db: Session, audience: str) -> User:
    """签名、TTL、用户状态与撤销版本都必须有效。"""
    try:
        token = request.cookies.get(f"yx_{audience}", "")
        ttl = (
            request.app.state.settings.admin_session_ttl
            if audience == "admin"
            else request.app.state.settings.session_ttl
        )
        payload = serializer(request, audience).loads(token, max_age=ttl)
        user = db.get(User, payload["id"])
        if user and user.status == "active" and user.session_version == payload["version"]:
            return user
    except (BadSignature, SignatureExpired, KeyError):
        pass
    raise DomainError("UNAUTHENTICATED", "请先登录", 401)


def set_cookie(request: Request, response, user: User, audience: str) -> None:
    """凭证只写 HttpOnly Cookie，不进入前端 localStorage。"""
    token = serializer(request, audience).dumps({"id": user.id, "version": user.session_version})
    response.set_cookie(
        f"yx_{audience}",
        token,
        httponly=True,
        secure=request.app.state.settings.app_env == "production",
        samesite="lax",
        max_age=request.app.state.settings.admin_session_ttl
        if audience == "admin"
        else request.app.state.settings.session_ttl,
        path=f"/api/v1/{audience}",
    )

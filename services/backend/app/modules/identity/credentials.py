"""受控管理员凭证；只保存随机盐的 PBKDF2 摘要，无公开管理注册入口。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.modules.identity.models import AdminCredential, User
from app.modules.operations.models import Audit

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """保存算法与迭代数，为未来升级保留验证能力。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    """常量时间比较，损坏或未知算法一律拒绝。"""
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        rounds = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= rounds <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds)
        return hmac.compare_digest(base64.b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


def provision_admin(
    db: Session, username: str, password: str, display_name: str, *, role: str = "admin"
) -> User:
    """CLI 或显式开发初始化专用；重复开通拒绝，不覆盖原密码。"""
    if role not in {"admin", "staff"}:
        raise DomainError("INVALID_ROLE", "仅受控开通管理或客服员工", 422)
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", username) or not 12 <= len(password) <= 128:
        raise DomainError("INVALID_ADMIN_CREDENTIAL", "账号须为 3–64 位小写标识，密码须为 12–128 位", 422)
    if not display_name.strip() or len(display_name) > 80:
        raise DomainError("INVALID_ADMIN_NAME", "显示名称须为 1–80 位", 422)
    if db.scalar(select(AdminCredential).where(AdminCredential.username == username)):
        raise DomainError("ADMIN_EXISTS", "管理员已开通；此命令不会覆盖原凭证")
    lookup = (
        "controlled:admin"
        if username == "admin"
        else "controlled:" + hashlib.sha256(username.encode()).hexdigest()[:48]
    )
    user = db.scalar(select(User).where(User.login_hash == lookup).with_for_update())
    if user is not None and (user.role != role or user.status != "active"):
        raise DomainError("ACCOUNT_UNAVAILABLE", "已有账户不可用于管理开通", 403)
    if user is None:
        user = User(login_hash=lookup, display_name=display_name, role=role)
        db.add(user)
        db.flush()
    db.add(AdminCredential(user_id=user.id, username=username, password_hash=hash_password(password)))
    db.add(
        Audit(
            actor_id=user.id,
            action="identity.admin_provisioned",
            resource_id=user.id,
            summary={"source": "controlled_bootstrap"},
        )
    )
    db.flush()
    return user

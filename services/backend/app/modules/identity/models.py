"""identity 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class User(Record, Base):
    """账户身份及可撤销会话版本；开发标识使用 HMAC，不保存手机号。"""

    __tablename__ = "users"
    __table_args__ = {"comment": "身份与角色；会话不能由前端声明"}
    login_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="手机号的密钥 HMAC 或受控管理员标识"
    )
    display_name: Mapped[str] = mapped_column(String(80), default="映序创作者", comment="公开昵称")
    role: Mapped[str] = mapped_column(
        String(16), default="customer", comment="customer/admin，管理账户受控创建"
    )
    status: Mapped[str] = mapped_column(String(16), default="active", comment="active/blocked/deleted")
    session_version: Mapped[int] = mapped_column(default=1, comment="退出登录时递增，撤销已有会话")


class AdminCredential(Record, Base):
    """后台专用凭证；角色依旧来自 users，不由客户端或凭证自行声明。"""

    __tablename__ = "admin_credentials"
    __table_args__ = {"comment": "通过受控 CLI 开通的管理员凭证"}
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, comment="管理账户")
    username: Mapped[str] = mapped_column(String(64), unique=True, comment="受控登录标识")
    password_hash: Mapped[str] = mapped_column(
        String(256), comment="算法、迭代数、随机盐和派生摘要；禁止公开返回"
    )

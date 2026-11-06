"""executions 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Plan(Record, Base):
    """不可覆盖的方案快照；修订必须分配新版本。"""

    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_no", name="uq_plan_version"),
        {"comment": "不可变方案、输入和权益快照"},
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, comment="所属项目")
    version_no: Mapped[int] = mapped_column(comment="项目内单调递增版本")
    brief_revision: Mapped[int] = mapped_column(comment="创建时项目需求版本")
    privacy_epoch: Mapped[int] = mapped_column(comment="创建时隐私版本")
    spec_json: Mapped[dict] = mapped_column(JSON, comment="schema_version=1 的冻结规格")
    input_manifest: Mapped[list] = mapped_column(JSON, comment="冻结资产、人物及授权版本")
    quota_snapshot: Mapped[dict] = mapped_column(JSON, comment="服务器计算的消耗")
    execution_policy: Mapped[dict] = mapped_column(JSON, comment="冻结供应商及配置摘要")
    content_hash: Mapped[str] = mapped_column(String(64), comment="方案规范化内容 SHA256")


class Approval(Record, Base):
    """确认卡与方案哈希绑定；一个卡只允许接受一次。"""

    __tablename__ = "execution_approvals"
    __table_args__ = {"comment": "待确认卡和接受记录"}
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), comment="所属项目")
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("plan_versions.id"), unique=True, comment="本阶段每版一张确认卡"
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/accepted/expired")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="UTC 到期时间")
    acceptance_key: Mapped[str | None] = mapped_column(String(100), comment="接受幂等键")


class Idempotency(Record, Base):
    """记录动作键与语义哈希；相同键不同内容拒绝。"""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("user_id", "scope", "key", name="uq_idempotency_scope"),
        {"comment": "原子动作防重记录"},
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), comment="动作拥有者")
    scope: Mapped[str] = mapped_column(String(100), comment="动作命名空间")
    key: Mapped[str] = mapped_column(String(100), comment="Idempotency-Key")
    fingerprint: Mapped[str] = mapped_column(String(64), comment="请求语义摘要")
    response_json: Mapped[dict] = mapped_column(JSON, comment="已提交动作的稳定响应")

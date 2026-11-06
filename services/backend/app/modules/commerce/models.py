"""commerce 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Account(Record, Base):
    """项目权益账户；可用、预占、已用三个桶在一个事务中变更。"""

    __tablename__ = "entitlement_accounts"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", name="uq_account_kind"),
        CheckConstraint("available >= 0 AND reserved >= 0 AND consumed >= 0", name="ck_quota_nonnegative"),
        {"comment": "非负的项目权益账户"},
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), comment="所属项目")
    kind: Mapped[str] = mapped_column(String(20), default="photo", comment="本阶段仅开放 photo")
    available: Mapped[int] = mapped_column(default=0, comment="可用次数")
    reserved: Mapped[int] = mapped_column(default=0, comment="已确认但未结算次数")
    consumed: Mapped[int] = mapped_column(default=0, comment="已成功交付次数")


class EntitlementEvent(Record, Base):
    """只追加流水；一项业务事件只能结算一次。"""

    __tablename__ = "entitlement_events"
    __table_args__ = {"comment": "权益变动事实与唯一结算键"}
    account_id: Mapped[str] = mapped_column(ForeignKey("entitlement_accounts.id"), comment="权益账户")
    event_key: Mapped[str] = mapped_column(String(120), unique=True, comment="grant/approval/job 事件唯一键")
    kind: Mapped[str] = mapped_column(String(20), comment="grant/reserve/consume/release")
    amount: Mapped[int] = mapped_column(comment="正整数次数")
    reason: Mapped[str] = mapped_column(String(120), comment="业务原因")

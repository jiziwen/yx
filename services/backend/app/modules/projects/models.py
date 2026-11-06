"""projects 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Project(Record, Base):
    """项目需求可更新，已确认方案不随需求或主题切换变化。"""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "client_request_key", name="uq_project_request"),
        {"comment": "拥有者隔离的创作项目"},
    )
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, comment="唯一拥有者")
    client_request_key: Mapped[str] = mapped_column(String(100), comment="建项目防重键")
    title: Mapped[str] = mapped_column(String(120), comment="项目标题")
    kind: Mapped[str] = mapped_column(String(16), comment="wedding/portrait")
    lifecycle: Mapped[str] = mapped_column(
        String(16), default="active", comment="active/archived/deleting/deleted"
    )
    brief_revision: Mapped[int] = mapped_column(default=1, comment="需求和参考集变化时递增")
    next_plan_version: Mapped[int] = mapped_column(default=1, comment="项目内下一方案号")
    privacy_epoch: Mapped[int] = mapped_column(default=0, comment="隐私授权代次，阻断旧任务提交")


class Subject(Record, Base):
    """人物授权声明；撤销后任务不得再使用冻结输入。"""

    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("project_id", "subject_key", name="uq_subject_key"),
        {"comment": "项目人物与授权版本"},
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, comment="所属项目")
    subject_key: Mapped[str] = mapped_column(String(20), comment="person_a/person_b")
    display_name: Mapped[str] = mapped_column(String(80), comment="人物显示名称")
    authorization_state: Mapped[str] = mapped_column(
        String(16), default="declared", comment="declared/revoked"
    )
    authorization_revision: Mapped[int] = mapped_column(default=1, comment="授权变更版本")
    declaration_version: Mapped[str] = mapped_column(String(16), default="v1", comment="已同意的授权声明版本")


class StudioDraft(Base):
    """当前创作的私有可变草稿，冻结方案仍由 executions 所有。"""

    __tablename__ = "studio_drafts"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    privacy_epoch: Mapped[int] = mapped_column()
    draft_json: Mapped[dict] = mapped_column(JSON, default=dict)

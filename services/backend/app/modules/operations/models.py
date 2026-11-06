"""operations 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Audit(Record, Base):
    """关键操作审计，载荷只含资源标识与必要事实。"""

    __tablename__ = "audit_logs"
    __table_args__ = {"comment": "敏感业务与运营动作审计"}
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), comment="操作账户")
    action: Mapped[str] = mapped_column(String(60), comment="动作名称")
    resource_id: Mapped[str] = mapped_column(String(36), comment="资源 ID")
    summary: Mapped[dict] = mapped_column(JSON, default=dict, comment="脱敏摘要，不含照片正文")


class ModelRelease(Record, Base):
    """不可变模型发布版本，只保存白名单设置和服务端编译的插件定义。"""

    __tablename__ = "model_releases"
    __table_args__ = {"comment": "302 模型配置历史，不含凭证"}
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), comment="发布管理员")
    revision: Mapped[int] = mapped_column(unique=True, comment="单调递增的模型发布版本")
    settings_json: Mapped[dict] = mapped_column(JSON, comment="受控模型、档位和能力配置")
    providers_json: Mapped[dict] = mapped_column(JSON, comment="不可变插件定义，密钥仅为变量名")
    routes_json: Mapped[dict] = mapped_column(JSON, comment="本版本启用的图片/语言模型路由")


class ModelSettingHead(Base):
    """模型发布指针与乐观锁，历史发布不得被覆盖。"""

    __tablename__ = "model_setting_heads"
    __table_args__ = {"comment": "模型配置当前版本指针"}
    key: Mapped[str] = mapped_column(String(16), primary_key=True, comment="固定 ai302 范围")
    revision: Mapped[int] = mapped_column(default=0, comment="并发编辑校验版本")
    release_id: Mapped[str | None] = mapped_column(ForeignKey("model_releases.id"), comment="当前发布")


class ModelCandidate(Record, Base):
    """候选设置与人工证据；保存候选不会改运行路由。"""

    __tablename__ = "model_candidates"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    settings_json: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    release_id: Mapped[str | None] = mapped_column(ForeignKey("model_releases.id"))


class QualityFeedback(Record, Base):
    """指定成片的一次质量处理，访问授权与一次补偿分别记录。"""

    __tablename__ = "quality_feedback"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), unique=True)
    reference_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    privacy_epoch: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="open")
    revision: Mapped[int] = mapped_column(default=1)
    grant_active: Mapped[bool] = mapped_column(default=True)
    assigned_staff_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    compensation_plan_id: Mapped[str | None] = mapped_column(ForeignKey("plan_versions.id"), unique=True)
    review_note: Mapped[str] = mapped_column(String(1000), default="")


class ModelCall(Record, Base):
    """管理员专属的模型请求/响应记录，不混入用户会话或普通审计。"""

    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_created_id", "created_at", "id"),)
    provider_id: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(200))
    operation: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    development_sample: Mapped[bool] = mapped_column(default=False)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    job_id: Mapped[str | None] = mapped_column(String(36))
    privacy_epoch: Mapped[int | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column()
    http_status: Mapped[int | None] = mapped_column()
    error_code: Mapped[str | None] = mapped_column(String(80))
    result_unknown: Mapped[bool] = mapped_column(default=False)
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict | list | str | None] = mapped_column(JSON, nullable=True)

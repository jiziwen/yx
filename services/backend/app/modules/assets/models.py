"""assets 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Asset(Record, Base):
    """只保存私有对象元信息，不在数据库保存照片字节。"""

    __tablename__ = "assets"
    __table_args__ = {"comment": "私有参考图及交付资产"}
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, comment="所属项目")
    subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("subjects.id"), comment="参考图绑定人物；成片为空"
    )
    source_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id"), unique=True, comment="每个 Job 一个主输出"
    )
    kind: Mapped[str] = mapped_column(String(20), comment="reference/photo")
    storage_key: Mapped[str] = mapped_column(
        String(160), unique=True, comment="私有存储对象键，不保存签名 URL"
    )
    mime_type: Mapped[str] = mapped_column(String(40), comment="服务端解码验证的 MIME")
    byte_size: Mapped[int] = mapped_column(comment="实际字节数")
    width: Mapped[int] = mapped_column(comment="像素宽度")
    height: Mapped[int] = mapped_column(comment="像素高度")
    checksum: Mapped[str] = mapped_column(String(64), comment="内容 SHA256")
    status: Mapped[str] = mapped_column(String(16), default="ready", comment="ready/deleting/deleted")
    development_sample: Mapped[bool] = mapped_column(default=False, comment="开发图片必须明确标记")


class AssetInput(Record, Base):
    """输出血缘用于撤销参考图后阻断派生文件。"""

    __tablename__ = "asset_inputs"
    __table_args__ = (
        UniqueConstraint("asset_id", "input_asset_id", name="uq_asset_input"),
        {"comment": "已生成资产的输入血缘"},
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True, comment="输出资产")
    input_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True, comment="输入参考图")

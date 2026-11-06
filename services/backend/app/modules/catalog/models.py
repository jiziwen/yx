"""动态主题目录的不可变图片、发布快照与版本指针。"""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class CatalogMaterial(Record, Base):
    """只接收管理员上传；对象键不对外暴露，公开访问由生效目录决定。"""

    __tablename__ = "catalog_materials"
    __table_args__ = (UniqueConstraint("actor_id", "request_key", name="uq_catalog_upload_request"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(36))
    storage_key: Mapped[str] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column()
    height: Mapped[int] = mapped_column()


class CatalogRelease(Record, Base):
    """完整目录及图片引用快照；保存即发布，不覆盖历史。"""

    __tablename__ = "catalog_releases"
    __table_args__ = (UniqueConstraint("actor_id", "request_key", name="uq_catalog_release_request"),)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(unique=True)
    style_id: Mapped[str] = mapped_column(String(80))
    request_json: Mapped[dict] = mapped_column(JSON)
    catalog_json: Mapped[dict] = mapped_column(JSON)
    images_json: Mapped[dict] = mapped_column(JSON)


class CatalogHead(Base):
    """固定catalog行用于发布并发校验，迁移时创建而非请求时隐式建表。"""

    __tablename__ = "catalog_heads"
    key: Mapped[str] = mapped_column(String(16), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    release_id: Mapped[str | None] = mapped_column(ForeignKey("catalog_releases.id"))

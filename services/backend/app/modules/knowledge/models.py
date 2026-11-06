"""知识版本、持久索引任务与固定向量空间；未发布版本不能进入用户检索。"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record

DIMENSIONS = 1536


class KnowledgeDocument(Record, Base):
    """发布指针和并发版本；客户标题、摘要均取发布版本。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "published_version_id"],
            ["knowledge_versions.document_id", "knowledge_versions.id"],
            name="fk_knowledge_published_version",
            use_alter=True,
        ),
    )
    revision: Mapped[int] = mapped_column(default=0)
    published_version_id: Mapped[str | None] = mapped_column(String(36))


class KnowledgeVersion(Record, Base):
    """ready 后内容不可修改；改正文重新导入，不覆盖旧索引。"""

    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no"),
        UniqueConstraint("document_id", "id"),
        UniqueConstraint("document_id", "request_key"),
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    version_no: Mapped[int] = mapped_column()
    request_key: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(20))
    source_key: Mapped[str] = mapped_column(String(200))
    source_format: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(50))
    embedding_spec: Mapped[dict] = mapped_column(JSON)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))


class KnowledgeChunk(Record, Base):
    """正文片段与同空间向量；SQLite 开发存 JSON，PostgreSQL 使用 vector(1536)。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("version_id", "ordinal"),)
    version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_versions.id"), index=True)
    ordinal: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(100))
    search_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(Vector(DIMENSIONS).with_variant(JSON(), "sqlite"))


class KnowledgeIndexJob(Record, Base):
    """系统知识队列，不占图片权益；调用后崩溃不透明补发付费 embedding。"""

    __tablename__ = "knowledge_index_jobs"
    version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_versions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(50))
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

"""知识发布、只读检索及授权引用契约，不向用户暴露任意块查询。"""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.core.schemas import Input
from app.core.views import View


class DocumentView(View):
    """后台文档发布版本；草稿元数据不从客户入口泄漏。"""

    id: str
    revision: int
    published_version_id: str | None
    created_at: datetime


class ImportVersion(Input):
    """JSON 文本导入；二进制 PDF 由 multipart 入口转换为同一服务。"""

    expected_revision: int = Field(ge=0)
    request_key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(default="", max_length=300)
    category: Literal["product", "photography", "wedding"] = "product"
    text: str = Field(min_length=1, max_length=60000)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def dates(self):
        """有效期使用带时区时间且严格递增。"""
        if any(value and value.tzinfo is None for value in (self.valid_from, self.valid_until)):
            raise ValueError("timezone required")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("invalid validity")
        return self


class PublishVersion(Input):
    """只有管理员显式发布；不提供 Agent 写入口。"""

    expected_revision: int = Field(ge=0)
    version_id: str


class VersionView(View):
    """索引状态、版本和公开内容预览，不返回原文对象键或凭证。"""

    id: str
    document_id: str
    version_no: int
    title: str
    summary: str
    category: str
    status: str
    error_code: str | None
    embedding_spec: dict
    valid_from: datetime | None
    valid_until: datetime | None
    approved_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ChunkPreview(View):
    """管理员发布前预览有限正文；没有嵌入向量或内部对象键。"""

    ordinal: int
    text: str
    locator: str


class GuideView(View):
    """指南标题、摘要与正文严格取当前有效发布版本。"""

    document_id: str
    version_id: str
    title: str
    summary: str
    category: str
    content: str | None = None


class SearchArguments(Input):
    """只接受问题文本，不接受文档 ID、权限或任意过滤 SQL。"""

    query: str = Field(min_length=1, max_length=160)


class Evidence(View):
    """本轮检索证据；模型只引用 chunk_id，最终由后端生成来源。"""

    chunk_id: str
    citation_key: str | None = None
    document_id: str
    version_id: str
    version_no: int
    title: str
    locator: str
    text: str


class SearchResult(View):
    """真实策略和有界证据；空结果需要明确不确定/人工入口。"""

    strategy: str
    evidence: list[Evidence]
    development_sample: bool


class CitationView(Evidence):
    """由检索记录验证生成的消息引用，不是模型自行填写的标题/原文。"""

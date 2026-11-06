"""记忆只接受可审阅的文字要求，不能携带执行、身份或价格字段。"""

from datetime import datetime
from typing import Annotated

from pydantic import Field, field_validator

from app.core.config import BriefFieldConfig
from app.core.schemas import Input
from app.core.views import View

Requirement = Annotated[str, Field(min_length=1, max_length=160)]
BriefValue = Annotated[str, Field(max_length=160)]


class MemoryInput(Input):
    """明确用户操作的完整替换；客户端必须携带当前版本和授权代次。"""

    expected_revision: int = Field(ge=0)
    expected_privacy_epoch: int = Field(ge=0)
    requirements: list[Requirement] = Field(max_length=12)
    source_run_id: str | None = Field(default=None, max_length=36)
    fields: dict[str, BriefValue] | None = Field(default=None, max_length=8)

    @field_validator("requirements")
    @classmethod
    def distinct(cls, values):
        """保留原顺序去重，清空使用显式空数组。"""
        return list(dict.fromkeys(values))


class MemoryView(View):
    """项目当前隐私代次的确认要求；禁用或撤销时不披露旧内容。"""

    project_id: str
    revision: int
    privacy_epoch: int
    requirements: list[str]
    updated_at: datetime | None
    enabled: bool
    max_items: int
    fields: dict[str, str] = Field(default_factory=dict)
    field_definitions: list[BriefFieldConfig] = Field(default_factory=list)

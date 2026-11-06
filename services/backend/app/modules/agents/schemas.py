"""Agent 入参和草稿白名单；没有执行、价格、身份、任意 URL 或供应商字段。"""

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.views import View
from app.modules.knowledge.schemas import CitationView
from app.modules.project_memory.schemas import BriefValue, MemoryView, Requirement
from app.modules.projects.api import Input

Mode = Literal["template", "portrait", "edit", "text"]
Keep = Literal["场景与构图", "人物与表情", "服装与造型"]


class DraftPatch(Input):
    """模型只建议可见表单字段，素材选择和授权不能由模型改变。"""

    intent: Literal["user_request", "suggestion"] = "suggestion"
    mode: Mode | None = None
    subject_only: bool | None = None
    shot_ids: list[str] | None = Field(default=None, max_length=12)
    style_shot_ids: list[str] | None = Field(default=None, max_length=12)
    reference_asset_ids: list[str] | None = Field(default=None, max_length=20)
    base_asset_id: str | None = None
    style_id: str | None = Field(default=None, max_length=100)
    aspect_ratio: str | None = None
    count: int | None = Field(default=None, ge=1, le=8)
    variants: int | None = Field(default=None, ge=1, le=8)
    mood: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    change: str | None = Field(default=None, max_length=1000)
    keep: list[Keep] | None = Field(default=None, max_length=3)


class DraftContext(Input):
    """本页未保存草稿的冻结副本；私有引用仍逐个校验归属和授权。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    mode: Mode
    subject_only: bool = False
    style_id: str = Field(max_length=100)
    aspect_ratio: str
    count: int = Field(ge=1, le=8)
    variants: int = Field(ge=1, le=8)
    mood: str = Field(max_length=120)
    notes: str = Field(max_length=1000)
    change: str = Field(max_length=1000)
    keep: list[Keep] = Field(max_length=3)
    reference_asset_ids: list[str] = Field(max_length=20)
    base_asset_id: str | None
    shot_ids: list[str] = Field(max_length=12)
    style_shot_ids: list[str] = Field(max_length=12)
    positions: dict[str, Literal["left", "right", "only"]] = Field(max_length=2)
    style_asset_ids: list[str] = Field(default_factory=list, max_length=12)


class AnalysisShot(Input):
    """显式选择一个当前目录样片，不接受图片URL。"""

    style_id: str = Field(max_length=100)
    shot_id: str = Field(max_length=100)


class SendMessage(Input):
    """客户端重试复用同一消息键和原始正文；版本冲突不悄悄覆盖草稿。"""

    client_message_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1200)
    expected_revision: int = Field(ge=1)
    expected_memory_revision: int | None = Field(default=None, ge=0)
    draft: DraftContext
    analysis_asset_ids: list[str] = Field(default_factory=list, max_length=4)
    analysis_shots: list[AnalysisShot] = Field(default_factory=list, max_length=4)
    analysis_consent: bool = False
    analysis_purpose: str = Field(default="", max_length=200)


class AgentAnswer(Input):
    """模型输出契约；追问和草稿都是完整终态，不等待用户期间占用 Worker。"""

    outcome: Literal["needs_input", "plan_ready", "answer"]
    reply: str = Field(min_length=1, max_length=1200)
    questions: list[str] = Field(default_factory=list, max_length=3)
    proposal: DraftPatch | None = None
    memory_suggestion: list[Requirement] = Field(default_factory=list, max_length=6)
    brief_suggestion: dict[str, BriefValue] | None = Field(default=None, max_length=8)
    tool_sources: list[str] = Field(default_factory=list, max_length=8)
    citations: list[str] = Field(default_factory=list, max_length=8)
    evidence_status: Literal["supported", "insufficient"] = "supported"

    @model_validator(mode="after")
    def coherent(self):
        """提案必须有实际字段；追问必须包含可回答的问题。"""
        if any(not question.strip() or len(question) > 160 for question in self.questions):
            raise ValueError("invalid questions")
        if self.outcome == "needs_input" and not self.questions:
            raise ValueError("questions required")
        if self.outcome == "plan_ready" and (
            self.proposal is None or not self.proposal.model_dump(exclude_none=True, exclude={"intent"})
        ):
            raise ValueError("proposal required")
        if self.outcome != "plan_ready" and self.proposal is not None:
            raise ValueError("proposal only for plan_ready")
        if self.evidence_status == "insufficient" and (
            self.proposal or self.citations or self.outcome == "plan_ready"
        ):
            raise ValueError("insufficient evidence cannot support a plan or citation")
        return self


class ToolCall(Input):
    """模型只能提交工具名和白名单参数，身份从服务端 Run 注入。"""

    name: str = Field(pattern=r"^[a-z_]{1,60}$")
    arguments: dict = Field(default_factory=dict, max_length=4)


class ToolRequest(Input):
    """一轮最多请求两个只读查询，不与最终回复混合。"""

    tool_calls: list[ToolCall] = Field(min_length=1, max_length=2)


class ToolObservation(View):
    """有真实读取时间的受控结果，错误也作为来源明确展示。"""

    id: str
    name: str
    title: str
    version: str
    status: Literal["ok", "error"]
    observed_at: datetime
    data: dict | None
    error_code: str | None


class ReplyPreview(View):
    """模型原生片段组成的临时文字；按调用尝试和序号替换，不执行提案。"""

    run_id: str
    attempt_no: int = Field(ge=1, le=4)
    seq: int = Field(ge=1)
    text: str = Field(max_length=1200)
    privacy_epoch: int = Field(ge=0)


class RunView(View):
    """公开运行事实，不披露提示词、凭证或隐藏推理。"""

    id: str
    primary_role: str = "creative"
    release_json: dict = Field(default_factory=dict)
    status: str
    stage: str
    outcome: str | None
    error_code: str | None
    model: str
    development_sample: bool
    calls: int
    reply_preview: ReplyPreview | None
    memory_revision: int
    tool_calls: int
    analysis_sources: list[dict] = Field(default_factory=list)
    draft_context: DraftContext | None
    brief_revision: int
    created_at: datetime
    finished_at: datetime | None


class MessageView(View):
    """项目当前隐私代次中已经提交的消息。"""

    id: str
    run_id: str
    seq: int
    role: str
    text: str
    proposal_json: DraftPatch | None
    memory_suggestion_json: list[str] | None
    brief_suggestion_json: dict[str, str] | None
    observations_json: list[ToolObservation] | None
    citations_json: list[CitationView] | None = None
    actor_id: str | None = None
    created_at: datetime


class ConversationView(View):
    """SSE 通知和定期校准共用的权威快照；不虚构 token 进度。"""

    id: str | None
    project_id: str
    privacy_epoch: int
    messages: list[MessageView]
    runs: list[RunView]
    model: str
    development_sample: bool
    enabled: bool
    memory: MemoryView
    older_cursor: str | None = None


class MessagePage(View):
    """按消息 seq 翻页，Run 随消息返回供旧提案核对；不执行任何模型调用。"""

    items: list[MessageView]
    runs: list[RunView]
    next_cursor: str | None
    privacy_epoch: int


class StepView(View):
    """运行诊断仅公开决策/尝试与来源Manifest，不公开隐藏推理。"""

    id: str
    seq: int
    kind: str
    name: str
    status: str
    manifest_json: dict
    usage_json: dict | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None

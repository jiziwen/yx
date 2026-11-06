"""用户可见 DTO；不把 ORM 的对象键、登录摘要或冻结内部策略直接返回。"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BindingView(BaseModel):
    """人物与样片位置的明确对应，不包含姓名或上游凭证。"""

    subject_id: str
    position: str


class InputView(BaseModel):
    """公开的冻结输入用途；只有项目私有 ID 或公开套系镜头 ID。"""

    source: str
    role: str
    asset_id: str | None = None
    subject_id: str | None = None
    style_id: str | None = None
    shot_id: str | None = None


class ItemView(BaseModel):
    """每个交付项的实际输入清单；按镜头拆分而非发送整组底图。"""

    inputs: list[InputView]
    shot_id: str | None = None

    aspect_ratio: str | None = None
    size: str | None = None


class View(BaseModel):
    """仅允许声明字段进入公开响应。"""

    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def utc_dates(cls, value):
        """SQLite 读取丢失时区时按统一 UTC 事实补回，避免前端按本地时间误解。"""
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
            )
        return value


class UserView(View):
    """当前登录身份摘要。"""

    id: str
    display_name: str
    role: str


class ProjectView(View):
    """项目列表和详情中的稳定字段。"""

    id: str
    title: str
    kind: str
    lifecycle: str
    brief_revision: int
    privacy_epoch: int
    created_at: datetime


class SubjectView(View):
    """可见人物及当前授权状态。"""

    id: str
    subject_key: str
    display_name: str
    authorization_state: str
    authorization_revision: int


class AssetView(View):
    """照片只公开授权 API 地址，不暴露私有对象键。"""

    id: str
    project_id: str
    subject_id: str | None
    source_job_id: str | None = None
    kind: str
    status: str
    width: int
    height: int
    development_sample: bool


class AccountView(View):
    """服务端权威权益，前端不自行扣减。"""

    available: int
    reserved: int
    consumed: int
    kind: str


class SpecView(View):
    """确认卡公开的固定创作规格。"""

    schema_version: int
    studio_draft_revision: int | None = None
    style_id: str
    style_version: str
    style_name: str
    kind: str
    aspect_ratio: str
    aspect_ratio_choice: str | None = None
    count: int
    mood: str
    notes: str
    reference_count: int
    mode: str = "portrait"
    operation: str = "reference"
    reference_asset_ids: list[str] = Field(default_factory=list)
    base_asset_id: str | None = None
    shot_ids: list[str] = Field(default_factory=list)
    style_shot_ids: list[str] = Field(default_factory=list)
    style_asset_ids: list[str] = Field(default_factory=list)
    variants: int = 1
    keep: list[str] = Field(default_factory=list)
    change: str = ""
    subject_bindings: list[BindingView] = Field(default_factory=list)
    items: list[ItemView] = Field(default_factory=list)
    subject_only: bool = False
    prompt_version: str | None = None
    prompt_policy_hash: str | None = None


class PlanView(View):
    """不可变方案和单独的确认状态。"""

    id: str
    version_no: int
    brief_revision: int
    spec_json: SpecView
    quota_snapshot: dict[str, int]
    approval_id: str
    approval_status: str
    expires_at: datetime


class JobView(View):
    """进度采用真实阶段，不制造供应商百分比。"""

    id: str
    item_index: int
    status: str
    revision: int
    error_code: str | None
    provider_id: str


class AcceptanceView(View):
    """确认请求的稳定结果，可在重复请求时原样返回。"""

    approval_id: str
    job_ids: list[str]


class ShotView(View):
    """套系样片来源仅为服务器注册内容。"""

    id: str
    name: str
    image: str
    position: str
    subject_slots: list[str]
    development_only: bool
    rights_approved: bool

    width: int | None = None
    height: int | None = None


class StyleView(View):
    """风格目录与界面主题分离。"""

    id: str
    version: str
    name: str
    theme_id: str
    image: str
    kind: str
    mood: str
    description: str = ""
    shots: list[ShotView]


class ModeCapabilityView(View):
    """由已安装路由和声明能力计算的公开限制。"""

    id: str
    operation: str
    max_input_images: int
    max_reference_images: int
    max_style_images: int
    max_subjects: int
    aspect_ratios: list[str]
    arbitrary_size: bool = True
    development_sample: bool


class UploadLimitsView(View):
    """项目素材保存上限，与单次模型限制独立。"""

    max_references_per_subject: int
    max_project_materials: int
    max_bytes: int


class CatalogView(View):
    """前端能力由后端已启用模块和开关共同决定。"""

    version: str
    styles: list[StyleView]
    aspect_ratios: list[str]
    max_count: int
    features: dict[str, bool]
    modules: list[str]
    development_mode: bool
    dev_login_enabled: bool
    trial_photo_count: int
    creation_modes: list[ModeCapabilityView]
    creation_prompt_policy_hash: str
    upload_limits: UploadLimitsView

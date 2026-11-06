"""运营模型表单只接受业务参数，不能提交密钥、上游 URL 或 Python 入口。"""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.core.schemas import Input
from app.core.views import View

ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")]
Operation = Literal["text", "reference", "edit"]


class ImageModelSettings(Input):
    """按操作配置图片模型，质量与能力必须显式登记。"""

    enabled: bool = False
    api: Literal["gpt", "unified"] = "gpt"
    text_model: ModelName = "gpt-image-2"
    reference_model: ModelName = "gpt-image-2"
    edit_model: ModelName = "gpt-image-2"
    quality: Literal["low", "medium", "high", "auto"] = "low"
    operations: list[Operation] = Field(
        default_factory=lambda: ["text", "reference", "edit"], min_length=1, max_length=3
    )
    max_input_images: int = Field(default=3, ge=0, le=20)
    max_reference_images: int = Field(default=2, ge=0, le=20)
    max_style_images: int = Field(default=1, ge=0, le=20)
    max_subjects: int = Field(default=2, ge=0, le=2)
    aspect_ratios: list[str] = Field(
        default_factory=lambda: ["3:4", "4:3", "1:1", "2:3", "3:2", "16:9", "9:16"],
        description="常用画幅选项，兼容历史配置，不作为模型尺寸限制",
    )

    @model_validator(mode="after")
    def validate_limits(self):
        """拒绝互相矛盾的限制，不能保存一个 UI 可选而模型配置无法执行的操作。"""
        if (
            len(set(self.operations)) != len(self.operations)
            or max(self.max_reference_images, self.max_style_images) > self.max_input_images
        ):
            raise ValueError("模型限制不一致")
        if "reference" in self.operations and (
            self.max_subjects < 1 or self.max_reference_images < self.max_subjects
        ):
            raise ValueError("人物参考能力不足")
        if "edit" in self.operations and self.max_input_images < 1:
            raise ValueError("编辑至少需要一张输入图片")
        return self


class LLMModelSettings(Input):
    """大语言模型只配置模型和输出预算，当前不自动开启 Agent 对话。"""

    enabled: bool = False
    model: ModelName = "claude-sonnet-5-5"
    max_tokens: int = Field(default=512, ge=32, le=4096)


class VisionModelSettings(LLMModelSettings):
    """视觉独立配置；只允许明确选图，输入字节和尺寸均有上限。"""

    max_input_images: int = Field(default=2, ge=1, le=4)
    max_dimension: int = Field(default=1024, ge=256, le=2048)
    max_bytes: int = Field(default=4000000, ge=100000, le=8000000)


class ModelSettingsInput(Input):
    """完整保存表单和期望版本，重复/陈旧编辑不能覆盖其他管理员的发布。"""

    expected_revision: int = Field(ge=0)
    image: ImageModelSettings
    llm: LLMModelSettings
    vision: VisionModelSettings = Field(default_factory=VisionModelSettings)


class ModelSettingsView(View):
    """凭证只报告是否存在，浏览器没有读取凭证值的接口。"""

    revision: int
    image: ImageModelSettings
    llm: LLMModelSettings
    vision: VisionModelSettings = Field(default_factory=VisionModelSettings)
    credentials_present: bool


class ProviderModelListView(View):
    """302 实际可见模型 ID，剔除任意上游扩展载荷。"""

    models: list[str]

"""版本化写真套系；可信本地素材在启动时解码并计算摘要，不接受浏览器文件路径。"""

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import DomainError
from app.modules.assets.service import normalize_image

MODES = {"template": "edit", "portrait": "reference", "edit": "edit", "text": "text"}


class ShotRights(BaseModel):
    """来源及三种用途独立审核，绑定标准化样片摘要。"""

    model_config = ConfigDict(extra="forbid")
    source_record: str = Field(default="", max_length=300)
    reviewed_by: str = Field(default="", max_length=100)
    checksum: str = ""
    display: bool = False
    derivative: bool = False
    model_processing: bool = False


class ShotConfig(BaseModel):
    """每个镜头对应独立可提交的素材，画面位置只用于界面裁切。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=100)
    file: str
    position: str = "50% 35%"
    rights: ShotRights = Field(default_factory=ShotRights)
    development_only: bool = False
    subject_slots: list[Literal["left", "right", "only"]] = Field(default_factory=lambda: ["only"])


class StyleConfig(BaseModel):
    """套系与外观主题关联可选；业务不依赖前端是否安装同名主题。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    version: str
    name: str
    theme_id: str
    image: str
    kind: Literal["portrait", "wedding"]
    mood: str
    enabled: bool = True
    description: str = ""
    shots: list[ShotConfig] = Field(default_factory=list, max_length=12)


class UploadLimits(BaseModel):
    """项目存储上限独立于每次模型输入限制。"""

    max_references_per_subject: int = Field(default=5, ge=1, le=20)
    max_project_materials: int = Field(default=20, ge=1, le=100)


class CatalogConfig(BaseModel):
    """配置无效在启动时失败，避免确认后才发现镜头不可用。"""

    model_config = ConfigDict(extra="forbid")
    version: str
    aspect_ratios: list[str]
    max_count: int = Field(ge=1, le=8)
    enabled_modes: list[Literal["template", "portrait", "edit", "text"]] = Field(
        default_factory=lambda: list(MODES)
    )
    upload_limits: UploadLimits = Field(default_factory=UploadLimits)
    styles: list[StyleConfig]


def load_catalog(path: Path, *, allow_development: bool = True) -> dict:
    """只读取配置目录内的授权素材，内部 PNG 字节不进入公开 DTO 或数据库。"""
    catalog = CatalogConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).model_dump()
    if len({style["id"] for style in catalog["styles"]}) != len(catalog["styles"]):
        raise ValueError("套系 ID 重复")
    if len(set(catalog["enabled_modes"])) != len(catalog["enabled_modes"]):
        raise ValueError("创作方式重复")
    images = {}
    root = path.parent.resolve()
    for style in catalog["styles"]:
        style["shots"] = [
            shot for shot in style["shots"] if allow_development or not shot["development_only"]
        ]
        if len({shot["id"] for shot in style["shots"]}) != len(style["shots"]):
            raise ValueError("套系镜头 ID 重复")
        for shot in style["shots"]:
            source = (root / shot.pop("file")).resolve()
            if not source.is_relative_to(root):
                raise ValueError("套系文件不能逃逸配置目录")
            if not shot["subject_slots"] or len(set(shot["subject_slots"])) != len(shot["subject_slots"]):
                raise ValueError("镜头人物位置无效")
            content, width, height = normalize_image(source.read_bytes())
            shot.update(width=width, height=height)
            shot["checksum"] = sha256(content).hexdigest()
            rights = shot["rights"]
            shot["rights_approved"] = bool(
                rights["source_record"]
                and rights["reviewed_by"]
                and rights["checksum"] == shot["checksum"]
                and all(rights[key] for key in ("display", "derivative", "model_processing"))
            )
            if not shot["development_only"] and not shot["rights_approved"]:
                raise ValueError("正式镜头必须审核来源、三种用途及匹配图片摘要")
            shot["image"] = f"/api/v1/web/inspiration/{style['id']}/{shot['id']}/content"
            images[(style["id"], shot["id"])] = content
    catalog["_images"] = images
    return catalog


def find_shot(catalog: dict, style_id: str, shot_id: str) -> dict:
    """关闭的套系或不存在的镜头不可作为新输入。"""
    style = next((s for s in catalog["styles"] if s["id"] == style_id and s["enabled"]), None)
    shot = next((s for s in style["shots"] if s["id"] == shot_id), None) if style else None
    if shot is None:
        raise DomainError("TEMPLATE_UNAVAILABLE", "套系或镜头已下架，请重新选择", 422)
    return shot


def verify_catalog_inputs(catalog: dict, manifest: list[dict]) -> None:
    """接受和外部提交前重新比对冻结镜头，配置更新不静默替换图片。"""
    for item in manifest:
        if item.get("source") == "catalog":
            shot = find_shot(catalog, item["style_id"], item["shot_id"])
            if shot["checksum"] != item["checksum"] or (
                item.get("usage_hash") and item["usage_hash"] != shot_usage_hash(shot)
            ):
                raise DomainError("TEMPLATE_CHANGED", "套系样片已更新，请保存新提案", 409)
            if not shot.get("development_only") and not shot.get("rights_approved"):
                raise DomainError("SHOT_USAGE_NOT_ALLOWED", "主题图片的创作或模型处理用途已撤回", 409)


def shot_usage_hash(shot):
    """用途撤回与停用也改变冻结输入，不只比对图片字节。"""
    return sha256(
        json.dumps(
            {
                "checksum": shot["checksum"],
                "rights": shot.get("rights", {}),
                "development_only": shot.get("development_only"),
                "enabled": shot.get("enabled", True),
                "subject_slots": shot.get("subject_slots", []),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

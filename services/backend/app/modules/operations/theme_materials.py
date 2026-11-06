"""管理员主题素材编辑：上传后私有预览，保存元数据与用途即可原子发布。"""

from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from pydantic import ConfigDict, Field, model_validator
from sqlalchemy import select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, AdminDep
from app.core.views import View
from app.modules.assets.service import normalize_image
from app.modules.catalog.live import CatalogImages, current_catalog
from app.modules.catalog.models import CatalogHead, CatalogMaterial, CatalogRelease
from app.modules.identity.models import User

from .models import Audit

router = APIRouter(tags=["theme-materials"])


class ThemeShotInput(Input):
    """角色和用途独立配置；图片只引用管理员上传ID，不能引用用户私有素材。"""

    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    name: str = Field(min_length=1, max_length=100)
    material_id: str | None = Field(default=None, max_length=36)
    position: str = Field(default="50% 35%", pattern=r"^\d{1,3}% \d{1,3}%$")
    subject_slots: list[Literal["left", "right", "only"]] = Field(min_length=1, max_length=3)
    enabled: bool = True
    source_record: str = Field(default="", max_length=300)
    display: bool = False
    derivative: bool = False
    model_processing: bool = False

    @model_validator(mode="after")
    def consistent(self):
        """任何用途都必须记录来源，人物位置不允许重复或混合单/双人定义。"""
        if (self.display or self.derivative or self.model_processing) and not self.source_record:
            raise ValueError("material source required")
        if len(set(self.subject_slots)) != len(self.subject_slots) or (
            "only" in self.subject_slots and len(self.subject_slots) > 1
        ):
            raise ValueError("invalid subject slots")
        if any(int(value.strip("%")) > 100 for value in self.position.split()):
            raise ValueError("invalid crop position")
        return self


class ThemeStyleInput(Input):
    """套系业务配置独立于前端外观主题插件；保存仅改受控元数据。"""

    id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["portrait", "wedding"]
    theme_id: str = Field(default="portrait", pattern=r"^[a-z0-9_-]{1,80}$")
    mood: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    shots: list[ThemeShotInput] = Field(max_length=12)

    @model_validator(mode="after")
    def unique_shots(self):
        """同套系镜头ID唯一，避免目录编号和图片引用出现歧义。"""
        if len({shot.id for shot in self.shots}) != len(self.shots):
            raise ValueError("duplicate shot id")
        return self


class ThemeSaveInput(Input):
    """同一发布动作可安全重试，旧全局目录版本不能覆盖其他管理员保存。"""

    request_key: UUID
    expected_revision: int = Field(ge=0)
    style: ThemeStyleInput


class ThemeMaterialView(View):
    """管理员上传结果不包含存储路径或原始文件名。"""

    id: str
    width: int
    height: int
    checksum: str
    image: str


class ThemeShotView(ThemeShotInput):
    """编辑器展示的版本图片；确认人及摘要由服务器记录。"""

    model_config = ConfigDict(extra="ignore")

    image: str
    checksum: str
    development_only: bool
    rights_approved: bool
    reviewed_by: str = ""


class ThemeStyleView(ThemeStyleInput):
    """当前保存的套系与镜头列表，包含已下架的管理条目。"""

    model_config = ConfigDict(extra="ignore")

    version: str
    shots: list[ThemeShotView]


class ThemeCatalogView(View):
    """编辑器读取当前版本，上传不改变这个目录版本。"""

    revision: int
    styles: list[ThemeStyleView]


class ThemeReleaseView(View):
    """不可变发布记录和操作者，保存即生效，无额外候选审批步骤。"""

    id: str
    revision: int
    style_id: str
    actor_id: str
    actor_name: str
    created_at: datetime


def material_view(row):
    """图片只有管理员可预览，发布后才由公开目录内容API提供。"""
    return {
        "id": row.id,
        "width": row.width,
        "height": row.height,
        "checksum": row.checksum,
        "image": f"/api/v1/admin/theme-materials/images/{row.id}/content",
    }


def editor_view(db, catalog, revision, release_id=None):
    """管理态包含隐藏镜头；启动YAML保持可编辑但不会自动被批准。"""
    styles = []
    for style in catalog["styles"]:
        shots = []
        for shot in style["shots"]:
            rights = shot.get("rights", {})
            material_id = shot.get("material_id")
            shots.append(
                {
                    **shot,
                    "enabled": shot.get("enabled", True),
                    "material_id": material_id,
                    "source_record": rights.get("source_record", ""),
                    **{key: rights.get(key, False) for key in ("display", "derivative", "model_processing")},
                    "reviewed_by": rights.get("reviewed_by", ""),
                    "image": f"/api/v1/admin/theme-materials/styles/{style['id']}/shots/{shot['id']}/content?checksum={shot['checksum']}"
                    + (f"&release_id={release_id}" if release_id else ""),
                }
            )
        styles.append({**style, "shots": shots})
    return {"revision": revision, "styles": styles}


@router.get("/api/v1/admin/theme-materials", response_model=ThemeCatalogView)
def get_themes(request: Request, user: AdminDep, db: DB):
    """读取实时全局目录版本；管理员不需要修改部署配置或重启。"""
    head = db.get(CatalogHead, "catalog")
    return editor_view(db, current_catalog(request.app, db, include_hidden=True), head.revision)


@router.post("/api/v1/admin/theme-materials/images", response_model=ThemeMaterialView)
async def upload_theme_image(
    request: Request, user: AdminDep, db: DB, request_key: UUID = Form(...), file: UploadFile = File(...)
):
    """服务端解码、去EXIF、尺寸/字节限制；不信任扩展名或浏览器摘要。"""
    raw = await file.read(request.app.state.settings.max_upload_bytes + 1)
    if len(raw) > request.app.state.settings.max_upload_bytes:
        raise DomainError("FILE_TOO_LARGE", "主题图片超过上传大小限制", 413)
    content, width, height = normalize_image(raw)
    checksum = sha256(content).hexdigest()
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(
        select(CatalogMaterial).where(
            CatalogMaterial.actor_id == user.id, CatalogMaterial.request_key == str(request_key)
        )
    )
    if existing:
        if existing.checksum != checksum:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一上传请求不能替换图片")
        return material_view(existing)
    row = CatalogMaterial(
        id=uid(),
        actor_id=user.id,
        request_key=str(request_key),
        storage_key=f"catalog/{uid()}.png",
        checksum=checksum,
        width=width,
        height=height,
    )
    storage = request.app.state.gateway.get("storage")
    storage.put(row.storage_key, content)
    try:
        db.add(row)
        db.add(
            Audit(
                actor_id=user.id,
                action="catalog.upload",
                resource_id=row.id,
                summary={"checksum": checksum, "width": width, "height": height},
            )
        )
        db.commit()
    except Exception:
        row_id, key = row.id, row.storage_key
        db.rollback()
        # 不删除提交结果尚不明确的对象；确定没有记录时才清理。
        with request.app.state.sessions() as check:
            if check.get(CatalogMaterial, row_id) is None:
                storage.delete(key)
        raise
    return material_view(row)


@router.get("/api/v1/admin/theme-materials/images/{material_id}/content")
def preview_upload(material_id: str, request: Request, user: AdminDep, db: DB):
    """只允许受控目录素材，不接收用户私有照片ID或任意文件路径。"""
    row = db.get(CatalogMaterial, material_id)
    if row is None:
        raise DomainError("NOT_FOUND", "主题图片不存在", 404)
    content = request.app.state.gateway.get("storage").get(row.storage_key)
    if sha256(content).hexdigest() != row.checksum:
        raise DomainError("TEMPLATE_CHANGED", "主题图片内容已变化", 409)
    return Response(content=content, media_type="image/png")


@router.get("/api/v1/admin/theme-materials/styles/{style_id}/shots/{shot_id}/content")
def preview_shot(
    style_id: str, shot_id: str, request: Request, user: AdminDep, db: DB, release_id: str | None = None
):
    """已停展示/下架素材仅管理员可从编辑器预览。"""
    if release_id:
        release = db.get(CatalogRelease, release_id)
        if release is None:
            raise DomainError("NOT_FOUND", "发布版本不存在", 404)
        catalog = {
            **release.catalog_json,
            "_images": CatalogImages(request.app, release.images_json, release.catalog_json),
        }
    else:
        catalog = current_catalog(request.app, db, include_hidden=True)
    style = next((style for style in catalog["styles"] if style["id"] == style_id), None)
    if not style or not any(shot["id"] == shot_id for shot in style["shots"]):
        raise DomainError("NOT_FOUND", "镜头不存在", 404)
    return Response(content=catalog["_images"][(style_id, shot_id)], media_type="image/png")


@router.get("/api/v1/admin/theme-materials/releases/{release_id}", response_model=ThemeCatalogView)
def theme_release_detail(release_id: str, request: Request, user: AdminDep, db: DB):
    """只读核对某次发布的来源、用途和原图，不会将旧版本重新发布。"""
    release = db.get(CatalogRelease, release_id)
    if release is None:
        raise DomainError("NOT_FOUND", "发布版本不存在", 404)
    return editor_view(db, release.catalog_json, release.revision, release.id)


@router.get("/api/v1/admin/theme-materials/releases", response_model=list[ThemeReleaseView])
def theme_releases(
    user: AdminDep, db: DB, offset: int = Query(default=0, ge=0), limit: int = Query(default=30, ge=1, le=100)
):
    """发布历史按版本倒序，不能覆盖历史来源和用途记录。"""
    return [
        {
            "id": release.id,
            "revision": release.revision,
            "style_id": release.style_id,
            "actor_id": actor.id,
            "actor_name": actor.display_name,
            "created_at": release.created_at,
        }
        for release, actor in db.execute(
            select(CatalogRelease, User)
            .join(User, User.id == CatalogRelease.actor_id)
            .order_by(CatalogRelease.revision.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/api/v1/admin/theme-materials", response_model=ThemeCatalogView)
def save_theme(body: ThemeSaveInput, request: Request, user: AdminDep, db: DB):
    """保存即发布；用途绑定当前字节和当前管理员，不伪造旧图片的来源记录。"""
    head = db.scalar(select(CatalogHead).where(CatalogHead.key == "catalog").with_for_update())
    payload = body.model_dump(mode="json")
    previous = db.scalar(
        select(CatalogRelease).where(
            CatalogRelease.actor_id == user.id, CatalogRelease.request_key == str(body.request_key)
        )
    )
    if previous:
        if previous.request_json != payload:
            raise DomainError("IDEMPOTENCY_CONFLICT", "同一保存请求不能用于不同内容")
        return editor_view(db, previous.catalog_json, previous.revision)
    if head.revision != body.expected_revision:
        raise DomainError("CATALOG_CONFLICT", "其他管理员已更新主题目录，请重新载入后保存")
    current = current_catalog(request.app, db, include_hidden=True)
    styles = current["styles"]
    old_style = next((style for style in styles if style["id"] == body.style.id), None)
    if old_style and old_style["kind"] != body.style.kind:
        raise DomainError("INVALID_SPEC", "已有套系不能改变项目类型，请新建另一个套系", 422)
    if not old_style and len(styles) >= 100:
        raise DomainError("CATALOG_LIMIT", "目录最多支持100个套系", 422)
    old_shots = {shot["id"]: shot for shot in old_style["shots"]} if old_style else {}
    images = dict(current.get("_stored_images", {}))
    shots = []
    for item in body.style.shots:
        old = old_shots.get(item.id)
        material_id = item.material_id or (old.get("material_id") if old else None)
        image_key = f"{body.style.id}/{item.id}"
        if material_id:
            material = db.get(CatalogMaterial, material_id)
            if material is None:
                raise DomainError("NOT_FOUND", "请先上传有效的主题图片", 404)
            content = request.app.state.gateway.get("storage").get(material.storage_key)
            if sha256(content).hexdigest() != material.checksum:
                raise DomainError("TEMPLATE_CHANGED", "上传的主题图片已变化，请重新上传", 409)
            checksum = material.checksum
            images[image_key] = {"storage_key": material.storage_key, "checksum": checksum}
        elif old:
            checksum = old["checksum"]
        else:
            raise DomainError("IMAGE_REQUIRED", "新镜头请先上传图片", 422)
        rights = {
            "source_record": item.source_record,
            "reviewed_by": user.id,
            "checksum": checksum,
            **item.model_dump(include={"display", "derivative", "model_processing"}),
        }
        development = bool(
            old
            and old.get("development_only")
            and (not item.material_id or item.material_id == old.get("material_id"))
            and not item.source_record
            and not any((item.display, item.derivative, item.model_processing))
        )
        shots.append(
            {
                "id": item.id,
                "name": item.name,
                "position": item.position,
                "width": material.width if material_id else old.get("width"),
                "height": material.height if material_id else old.get("height"),
                "subject_slots": item.subject_slots,
                "material_id": material_id,
                "enabled": item.enabled,
                "rights": rights,
                "checksum": checksum,
                "development_only": development,
                "rights_approved": bool(
                    item.source_record and item.display and item.derivative and item.model_processing
                ),
                "image": f"/api/v1/web/inspiration/{body.style.id}/{item.id}/content?checksum={checksum}",
            }
        )
    style = {
        **body.style.model_dump(exclude={"shots"}),
        "shots": shots,
        "version": f"published-{head.revision + 1}",
    }
    cover = next((shot["image"] for shot in shots if shot["enabled"] and shot["rights"]["display"]), None)
    style["image"] = cover or (
        old_style["image"]
        if old_style and old_style["image"].startswith("/images/")
        else "/images/theme-muse.webp"
    )
    catalog = {key: value for key, value in current.items() if not key.startswith("_")}
    catalog["styles"] = [style if entry["id"] == style["id"] else entry for entry in styles]
    if not old_style:
        catalog["styles"].append(style)
    revision = head.revision + 1
    catalog["version"] = f"published-{revision}"
    release = CatalogRelease(
        id=uid(),
        actor_id=user.id,
        request_key=str(body.request_key),
        revision=revision,
        style_id=style["id"],
        request_json=payload,
        catalog_json=catalog,
        images_json=images,
    )
    db.add(release)
    db.flush()
    head.revision, head.release_id = revision, release.id
    db.add(
        Audit(
            actor_id=user.id,
            action="catalog.publish",
            resource_id=release.id,
            summary={"revision": revision, "style_id": style["id"], "shot_count": len(shots)},
        )
    )
    db.commit()
    return editor_view(db, catalog, revision)

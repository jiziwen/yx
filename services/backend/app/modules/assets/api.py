"""开发私有上传/读取入口；照片始终经拥有者和授权守卫访问。"""

from hashlib import sha256
from typing import Literal

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from sqlalchemy import select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.security import DB, UserDep
from app.core.views import AssetView
from app.modules.project_memory.retention import KeepPreferences, retain_preferences, selected_preferences
from app.modules.projects.models import Subject
from app.modules.projects.service import require_project

from .models import Asset
from .service import assert_accessible, normalize_image

router = APIRouter(tags=["assets"])


@router.post("/api/v1/web/projects/{project_id}/uploads", response_model=AssetView)
async def upload(
    project_id: str,
    request: Request,
    user: UserDep,
    db: DB,
    subject_id: str | None = Form(default=None),
    purpose: Literal["reference", "base", "style"] = Form(default="reference"),
    declared: bool = Form(default=False),
    file: UploadFile = File(),
):
    """本地开发通过 API 限量上传；不保存客户端文件名和 EXIF。"""
    project = require_project(db, project_id, user.id, writable=True)
    subject = db.get(Subject, subject_id) if subject_id else None
    if purpose == "reference" and (
        subject is None or subject.project_id != project.id or subject.authorization_state != "declared"
    ):
        raise DomainError("NOT_FOUND", "人物不存在或授权已撤销", 404)
    if purpose != "reference" and (subject_id is not None or not declared):
        raise DomainError("IMAGE_RIGHTS_REQUIRED", "请确认有权使用这张底图或风格参考", 422)
    content = await file.read(request.app.state.settings.max_upload_bytes + 1)
    await file.close()
    if len(content) > request.app.state.settings.max_upload_bytes:
        raise DomainError("UPLOAD_TOO_LARGE", "图片不能超过 10 MB", 413)
    limits = request.app.state.catalog["upload_limits"]
    existing_count = len(
        list(
            db.scalars(
                select(Asset.id).where(
                    Asset.subject_id == subject_id, Asset.kind == "reference", Asset.status == "ready"
                )
            )
        )
    )
    materials_count = len(
        list(
            db.scalars(
                select(Asset.id).where(
                    Asset.project_id == project.id,
                    Asset.kind.in_(["reference", "base", "style"]),
                    Asset.status == "ready",
                )
            )
        )
    )
    if materials_count >= limits["max_project_materials"] or (
        purpose == "reference" and existing_count >= limits["max_references_per_subject"]
    ):
        raise DomainError("REFERENCE_LIMIT", "项目或人物已达到素材保存上限，请先整理已有素材", 422)
    content, width, height = normalize_image(content)
    asset_id = uid()
    key = f"{project.id}/{asset_id}.png"
    storage = request.app.state.gateway.get("storage")
    storage.put(key, content)
    try:
        asset = Asset(
            id=asset_id,
            project_id=project.id,
            subject_id=subject.id if subject else None,
            kind=purpose,
            storage_key=key,
            mime_type="image/png",
            byte_size=len(content),
            width=width,
            height=height,
            checksum=sha256(content).hexdigest(),
        )
        db.add(asset)
        project.brief_revision += 1
        db.commit()
    except Exception:
        storage.delete(key)
        raise
    return asset


@router.get("/api/v1/web/projects/{project_id}/assets", response_model=list[AssetView])
def list_assets(project_id: str, user: UserDep, db: DB):
    """列表不包含已经撤销人物的图片。"""
    require_project(db, project_id, user.id)
    items = []
    for asset in db.scalars(
        select(Asset)
        .where(Asset.project_id == project_id, Asset.status == "ready")
        .order_by(Asset.created_at)
    ):
        try:
            assert_accessible(db, asset)
            items.append(asset)
        except DomainError:
            continue
    return items


@router.get("/api/v1/web/assets/{asset_id}/content")
def content(asset_id: str, request: Request, user: UserDep, db: DB, download: bool = False):
    """认证代理式读取支持即时撤销，禁止共享/浏览器公共缓存。"""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise DomainError("NOT_FOUND", "文件不可访问", 404)
    require_project(db, asset.project_id, user.id)
    assert_accessible(db, asset)
    try:
        data = request.app.state.gateway.get("storage").get(asset.storage_key)
    except FileNotFoundError as exc:
        raise DomainError("ASSET_UNAVAILABLE", "文件暂不可用", 404) from exc
    return Response(
        content=data,
        media_type=asset.mime_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'{"attachment" if download else "inline"}; filename="yingxu-{asset.id}.png"',
        },
    )


@router.delete("/api/v1/web/assets/{asset_id}")
def delete_asset(asset_id: str, user: UserDep, db: DB, body: KeepPreferences | None = None):
    """先持久化访问屏障，维护进程负责物理清理与派生资产。"""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise DomainError("NOT_FOUND", "文件不可访问", 404)
    project = require_project(db, asset.project_id, user.id, lock=True)
    selected = selected_preferences(db, project, body)
    asset.status = "deleting"
    project.privacy_epoch += 1
    project.brief_revision += 1
    retain_preferences(db, project, user.id, selected)
    db.commit()
    return {"ok": True, "cleanup": "pending"}

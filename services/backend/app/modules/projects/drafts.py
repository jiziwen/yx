"""左右工作室共享的私有草稿；不调用模型、不创建确认或付费任务。"""

from fastapi import APIRouter
from pydantic import Field

from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, UserDep
from app.core.views import View
from app.modules.agents.schemas import DraftContext
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible

from .models import StudioDraft
from .service import require_project

router = APIRouter(tags=["studio"])


class StudioDraftInput(Input):
    """显式版本与隐私代次防止多窗口覆盖和删除后恢复旧素材。"""

    expected_revision: int = Field(ge=0)
    expected_privacy_epoch: int = Field(ge=0)
    draft: DraftContext


class StudioDraftView(View):
    """只有拥有者可读，旧授权代次正文立即不可见。"""

    revision: int
    privacy_epoch: int
    draft: DraftContext | None


def view_draft(db, project):
    """保留版本供冲突判断，过期内容不返回。"""
    row = db.get(StudioDraft, project.id)
    return {
        "revision": row.revision if row else 0,
        "privacy_epoch": project.privacy_epoch,
        "draft": row.draft_json if row and row.privacy_epoch == project.privacy_epoch else None,
    }


@router.get("/api/v1/web/projects/{project_id}/studio-draft", response_model=StudioDraftView)
def get_draft(project_id: str, user: UserDep, db: DB):
    """读私有草稿不触发写入或模型调用。"""
    return view_draft(db, require_project(db, project_id, user.id))


@router.put("/api/v1/web/projects/{project_id}/studio-draft", response_model=StudioDraftView)
def put_draft(project_id: str, body: StudioDraftInput, user: UserDep, db: DB):
    """允许未完整填写的草稿；引用仍逐个验证，不保存任意对象。"""
    project = require_project(db, project_id, user.id, writable=True)
    row = db.get(StudioDraft, project.id)
    if body.expected_privacy_epoch != project.privacy_epoch:
        raise DomainError("AUTHORIZATION_CHANGED", "素材授权已变化，请重新选择")
    if body.expected_revision != (row.revision if row else 0):
        raise DomainError("DRAFT_CONFLICT", "另一窗口更新了创作草稿，请选择载入最新版本")
    refs = set(body.draft.reference_asset_ids + body.draft.style_asset_ids)
    if body.draft.base_asset_id:
        refs.add(body.draft.base_asset_id)
    for asset_id in refs:
        asset = db.get(Asset, asset_id)
        if asset is None or asset.project_id != project.id:
            raise DomainError("NOT_FOUND", "素材不可访问", 404)
        assert_accessible(db, asset)
        if asset_id in body.draft.reference_asset_ids and asset.kind != "reference":
            raise DomainError("INVALID_REFERENCE", "人物参考用途不匹配", 422)
        if asset_id in body.draft.style_asset_ids and asset.kind != "style":
            raise DomainError("INVALID_STYLE", "风格参考用途不匹配", 422)
        if asset_id == body.draft.base_asset_id and asset.kind not in {"base", "photo"}:
            raise DomainError("INVALID_BASE", "底图用途不匹配", 422)
    if row is None:
        row = StudioDraft(project_id=project.id, revision=0, privacy_epoch=project.privacy_epoch)
        db.add(row)
    if row.privacy_epoch == project.privacy_epoch and row.draft_json == body.draft.model_dump():
        return view_draft(db, project)
    row.revision += 1
    row.privacy_epoch, row.draft_json = project.privacy_epoch, body.draft.model_dump()
    db.commit()
    return view_draft(db, project)

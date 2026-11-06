"""固定表单创作接口；每次修改创建新方案，不覆盖历史。"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from app.core.schemas import Input
from app.core.security import DB, UserDep
from app.core.views import AcceptanceView, PlanView
from app.modules.catalog.live import current_catalog
from app.modules.projects.api import Key
from app.modules.projects.service import require_project

from .models import Plan
from .service import accept_plan, create_plan, plan_view

router = APIRouter(tags=["executions"])


class SubjectBinding(Input):
    """用户明确指定人物在底图中的位置。"""

    subject_id: str = Field(max_length=80)
    position: Literal["left", "right", "only"]


class PlanInput(Input):
    """服务器白名单规格；客户端不能指定权益消耗或供应商。"""

    style_id: str = Field(max_length=80)
    style_version: str = Field(max_length=20)
    aspect_ratio: str
    count: int = Field(ge=1, le=8)
    mood: str = Field(min_length=1, max_length=120)
    notes: str = Field(max_length=1000, default="")
    expected_revision: int = Field(ge=1)
    studio_draft_revision: int | None = Field(default=None, ge=1)
    mode: Literal["template", "portrait", "edit", "text"] | None = None
    subject_only: bool | None = None
    reference_asset_ids: list[str] | None = Field(default=None, max_length=20)
    base_asset_id: str | None = Field(default=None, max_length=80)
    shot_ids: list[str] = Field(default_factory=list, max_length=12)
    style_shot_ids: list[str] = Field(default_factory=list, max_length=12)
    style_asset_ids: list[str] = Field(default_factory=list, max_length=12)
    variants: int = Field(default=1, ge=1, le=8)
    keep: list[Literal["场景与构图", "人物与表情", "服装与造型"]] = Field(default_factory=list, max_length=3)
    change: str = Field(default="", max_length=1000)
    subject_bindings: list[SubjectBinding] = Field(default_factory=list, max_length=2)


@router.get("/api/v1/web/projects/{project_id}/plans", response_model=list[PlanView])
def plans(project_id: str, user: UserDep, db: DB):
    """按版本倒序返回历史，确认状态由独立确认表提供。"""
    require_project(db, project_id, user.id)
    return [
        plan_view(db, plan)
        for plan in db.scalars(
            select(Plan).where(Plan.project_id == project_id).order_by(Plan.version_no.desc()).limit(50)
        )
    ]


@router.post("/api/v1/web/projects/{project_id}/plans", response_model=PlanView)
def save_plan(project_id: str, body: PlanInput, key: Key, request: Request, user: UserDep, db: DB):
    """表单只保存方案和确认卡，不触发图片生成。"""
    plan = create_plan(
        db, project_id, user.id, body, key, current_catalog(request.app, db), request.app.state.gateway
    )
    return plan_view(db, plan)


@router.post("/api/v1/web/approvals/{approval_id}/accept", response_model=AcceptanceView)
def accept(approval_id: str, key: Key, request: Request, user: UserDep, db: DB):
    """明确用户确认后才预占权益并原子创建任务。"""
    from evals.m25_runtime import check as check_experiment

    check_experiment(request.app.state.settings, paid=True)
    return accept_plan(
        db, approval_id, user.id, key, request.app.state.gateway, current_catalog(request.app, db)
    )

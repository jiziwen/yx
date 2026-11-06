"""指定作品质量反馈、最小看图授权和一次人工补偿；生成仍由拥有者确认。"""

from copy import deepcopy
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from app.core.db import now
from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, StaffDep, UserDep
from app.modules.agents.context import fingerprint
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible, verify_inputs
from app.modules.executions.models import Approval, Plan
from app.modules.executions.service import plan_view
from app.modules.media_jobs.models import Job
from app.modules.projects.models import Project
from app.modules.projects.service import require_project

from .models import Audit, QualityFeedback

router = APIRouter(tags=["quality-feedback"])


class FeedbackInput(Input):
    """授权只覆盖这张成片与可选的一张参考，不扩散到项目。"""

    asset_id: str
    reference_asset_id: str | None = None
    reason: str = Field(min_length=3, max_length=1000)
    grant_view: Literal[True]


class FeedbackAction(Input):
    """每次领取、退出、审核都验证用户看到的版本。"""

    expected_revision: int = Field(ge=1)
    action: Literal["claim", "approve_redo", "close", "withdraw"]
    note: str = Field(default="", max_length=1000)


def view(db, row, *, include_plan=True):
    """审核记录和补偿确认卡可追溯，不返回任意项目文件。"""
    plan = db.get(Plan, row.compensation_plan_id) if row.compensation_plan_id else None
    return {
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "project_id",
                "asset_id",
                "reference_asset_id",
                "reason",
                "status",
                "revision",
                "grant_active",
                "assigned_staff_id",
                "review_note",
            )
        },
        "plan": plan_view(db, plan) if plan and include_plan else None,
    }


def current(db, row):
    """撤销、隐私代次变化、结单及30天期限每次读取复核。"""
    project = db.get(Project, row.project_id)
    from app.workers.agent_runtime import aware

    if (
        not project
        or project.lifecycle != "active"
        or row.privacy_epoch != project.privacy_epoch
        or not row.grant_active
        or row.status in {"closed", "withdrawn"}
        or aware(row.created_at) + timedelta(days=30) <= now()
    ):
        raise DomainError("FEEDBACK_ACCESS_REVOKED", "反馈授权已失效", 403)
    return project


@router.post("/api/v1/web/projects/{project_id}/feedback", status_code=201)
def submit(project_id: str, body: FeedbackInput, user: UserDep, db: DB):
    """同一原作品仅一个质量问题记录，重复提交不会重复补偿。"""
    project = require_project(db, project_id, user.id, writable=True)
    asset = db.get(Asset, body.asset_id)
    if not asset or asset.project_id != project.id or asset.kind != "photo":
        raise DomainError("NOT_FOUND", "作品不可访问", 404)
    assert_accessible(db, asset)
    if body.reference_asset_id:
        reference = db.get(Asset, body.reference_asset_id)
        if not reference or reference.project_id != project.id or reference.kind != "reference":
            raise DomainError("NOT_FOUND", "参考图不可访问", 404)
        assert_accessible(db, reference)
    existing = db.scalar(select(QualityFeedback).where(QualityFeedback.asset_id == asset.id))
    if existing:
        if existing.reason != body.reason or existing.reference_asset_id != body.reference_asset_id:
            raise DomainError("FEEDBACK_EXISTS", "这张作品已有质量反馈，请查看原记录")
        return view(db, existing)
    row = QualityFeedback(
        project_id=project.id,
        asset_id=asset.id,
        reference_asset_id=body.reference_asset_id,
        privacy_epoch=project.privacy_epoch,
        reason=body.reason,
    )
    db.add(row)
    db.commit()
    return view(db, row)


@router.get("/api/v1/web/projects/{project_id}/feedback")
def user_feedback(project_id: str, user: UserDep, db: DB):
    """拥有者读取当前授权代次的反馈和补偿卡。"""
    project = require_project(db, project_id, user.id)
    return [
        view(db, row)
        for row in db.scalars(
            select(QualityFeedback).where(
                QualityFeedback.project_id == project.id,
                QualityFeedback.privacy_epoch == project.privacy_epoch,
            )
        )
    ]


@router.get("/api/v1/admin/quality-feedback")
def staff_list(user: StaffDep, db: DB):
    """只返回尚未领取或本人负责的有效工单。"""
    result = []
    for row in db.scalars(
        select(QualityFeedback)
        .where(QualityFeedback.status.in_(["open", "claimed", "approved"]))
        .order_by(QualityFeedback.created_at)
        .limit(100)
    ):
        if row.assigned_staff_id not in (None, user.id):
            continue
        try:
            current(db, row)
            result.append(view(db, row, include_plan=False))
        except DomainError:
            continue
    return result


def action(db, row, actor, body, *, staff):
    """按项目→工单锁序保证领取和一次补偿互斥。"""
    if row.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "反馈已更新，请刷新")
    current(db, row)
    if staff:
        if body.action == "claim" and row.assigned_staff_id is None:
            row.assigned_staff_id, row.status = actor.id, "claimed"
        elif row.assigned_staff_id != actor.id:
            raise DomainError("PERMISSION_DENIED", "请先领取此工单", 403)
        elif body.action == "approve_redo":
            if len(body.note.strip()) < 3:
                raise DomainError("REVIEW_REQUIRED", "请说明质量问题和补偿理由", 422)
            if row.compensation_plan_id:
                raise DomainError("COMPENSATION_USED", "此质量问题已经批准过一次补偿")
            asset = db.get(Asset, row.asset_id)
            job = db.get(Job, asset.source_job_id)
            original = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
            if original.spec_json.get("compensation_feedback_id"):
                raise DomainError("COMPENSATION_USED", "补偿作品不能再次发放同类补偿")
            project = db.get(Project, row.project_id)
            verify_inputs(db, project, original.input_manifest, original.privacy_epoch)
            spec = deepcopy(original.spec_json)
            spec.update(
                count=1,
                studio_draft_revision=None,
                compensation_feedback_id=row.id,
                compensation_source_asset_id=asset.id,
            )
            if spec.get("items"):
                spec["items"] = [spec["items"][job.item_index - 1]]
            plan = Plan(
                project_id=project.id,
                version_no=project.next_plan_version,
                brief_revision=project.brief_revision,
                privacy_epoch=project.privacy_epoch,
                spec_json=spec,
                input_manifest=original.input_manifest,
                quota_snapshot={"photo": 0},
                execution_policy=original.execution_policy,
                content_hash=fingerprint(spec),
            )
            project.next_plan_version += 1
            db.add(plan)
            db.flush()
            db.add(
                Approval(project_id=project.id, plan_version_id=plan.id, expires_at=now() + timedelta(days=7))
            )
            row.compensation_plan_id, row.status, row.review_note = plan.id, "approved", body.note
        elif body.action == "close":
            row.status, row.grant_active = "closed", False
        else:
            raise DomainError("INVALID_ACTION", "操作不可用", 422)
    elif body.action == "withdraw":
        row.status, row.grant_active = "withdrawn", False
    else:
        raise DomainError("PERMISSION_DENIED", "用户不能批准补偿", 403)
    row.revision += 1
    db.add(
        Audit(
            actor_id=actor.id,
            action="quality_feedback." + body.action,
            resource_id=row.id,
            summary={"revision": row.revision},
        )
    )
    db.commit()
    return view(db, row, include_plan=not staff)


@router.post("/api/v1/web/quality-feedback/{feedback_id}/action")
def user_action(feedback_id: str, body: FeedbackAction, user: UserDep, db: DB):
    """用户可随时撤回查看授权，新文件访问立即停止。"""
    row = db.get(QualityFeedback, feedback_id)
    if not row:
        raise DomainError("NOT_FOUND", "反馈不存在", 404)
    require_project(db, row.project_id, user.id, lock=True)
    db.refresh(row, with_for_update=True)
    return action(db, row, user, body, staff=False)


@router.post("/api/v1/admin/quality-feedback/{feedback_id}/action")
def staff_action(feedback_id: str, body: FeedbackAction, user: StaffDep, db: DB):
    """员工审核不产生任务，只准备零用户次数的独立确认卡。"""
    row = db.get(QualityFeedback, feedback_id)
    if not row:
        raise DomainError("NOT_FOUND", "反馈不存在", 404)
    db.scalar(select(Project).where(Project.id == row.project_id).with_for_update())
    db.refresh(row, with_for_update=True)
    return action(db, row, user, body, staff=True)


@router.get("/api/v1/admin/quality-feedback/{feedback_id}/assets/{asset_id}")
def staff_image(feedback_id: str, asset_id: str, user: StaffDep, db: DB, request: Request):
    """认证代理逐次复核，没有可转发签名URL；不承诺回收已看过的内容。"""
    row = db.get(QualityFeedback, feedback_id)
    if not row or row.assigned_staff_id != user.id or asset_id not in {row.asset_id, row.reference_asset_id}:
        raise DomainError("NOT_FOUND", "图片未授权", 404)
    current(db, row)
    asset = db.get(Asset, asset_id)
    assert_accessible(db, asset)
    data = request.app.state.gateway.get("storage").get(asset.storage_key)
    db.add(
        Audit(
            actor_id=user.id,
            action="quality_feedback.view_image",
            resource_id=row.id,
            summary={"asset_id": asset_id},
        )
    )
    db.commit()
    return Response(
        data,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )

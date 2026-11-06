"""运营只读调用证据与受控核对入口，不提供强制成功或重新提交。"""

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.db import now
from app.core.errors import DomainError
from app.core.security import DB, AdminDep
from app.integrations.contracts import AsyncImageProvider
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.governance import aware
from app.modules.media_jobs.models import Job, ProviderAttempt
from app.modules.media_jobs.service import TERMINAL, cancel
from app.workers.runtime import reconcile_job

from .models import Audit
from .schemas import JobActionInput, JobDetailView

router = APIRouter()


def require_job(db, job_id, *, locked=False):
    """管理身份通过后仍校验资源存在；所有变更按 Job 行锁串行。"""
    query = select(Job).where(Job.id == job_id)
    job = db.scalar(query.with_for_update() if locked else query)
    if job is None:
        raise DomainError("NOT_FOUND", "任务不存在", 404)
    return job


def detail(app, db, job):
    """从事实计算可恢复性，明确缺少凭据和不兼容配置的边界。"""
    attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
    reason = "not_submitted"
    if job.status in TERMINAL:
        reason = "terminal"
    elif attempt:
        reason = "missing_receipt" if not attempt.upstream_task_id else "unsupported"
        if attempt.upstream_task_id:
            try:
                provider = app.state.gateway.get("image", job.provider_id)
                plan = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
                if app.state.gateway.snapshot("image", job.provider_id) != plan.execution_policy:
                    reason = "config_changed"
                elif isinstance(provider, AsyncImageProvider):
                    reason = (
                        "querying"
                        if attempt.lookup_lease_until and aware(attempt.lookup_lease_until) > now()
                        else "ready"
                    )
            except ValueError:
                reason = "config_changed"
    return {
        "job": job,
        "revision": job.revision,
        "can_reconcile": reason == "ready",
        "recovery_reason": reason,
        "attempt": {
            "request_key": attempt.request_key,
            "status": attempt.status,
            "error_code": attempt.error_code,
            "receipt_recorded": bool(attempt.upstream_task_id),
            "created_at": attempt.created_at,
            "finished_at": attempt.finished_at,
            "next_poll_at": attempt.next_poll_at,
            "latency_ms": attempt.latency_ms,
            "usage": attempt.usage_json,
            "estimated_cost_micros": attempt.estimated_cost_micros,
            "estimated_currency": attempt.estimated_currency,
            "actual_cost_micros": attempt.actual_cost_micros,
            "currency": attempt.currency,
        }
        if attempt
        else None,
    }


@router.get("/api/v1/admin/jobs/{job_id}", response_model=JobDetailView)
def job_detail(job_id: str, request: Request, user: AdminDep, db: DB):
    """详情只含脱敏调用事实，管理员也不获得用户照片入口。"""
    return detail(request.app, db, require_job(db, job_id))


@router.post("/api/v1/admin/jobs/{job_id}/reconcile", response_model=JobDetailView)
def reconcile(job_id: str, body: JobActionInput, request: Request, user: AdminDep, db: DB):
    """审计核对意图后释放事务，仅查询原供应商任务。"""
    job = require_job(db, job_id, locked=True)
    if job.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "任务状态已变化，请刷新后核对")
    snapshot = detail(request.app, db, job)
    if not snapshot["can_reconcile"]:
        raise DomainError("RECONCILIATION_UNAVAILABLE", "当前无法自动核对，请查看调用详情")
    db.add(
        Audit(
            actor_id=user.id,
            action="job.reconcile",
            resource_id=job.id,
            summary={"revision": job.revision, "request_key": snapshot["attempt"]["request_key"]},
        )
    )
    db.commit()
    reconcile_job(request.app, job.id, force=True)
    db.expire_all()
    return detail(request.app, db, require_job(db, job_id))


@router.post("/api/v1/admin/jobs/{job_id}/cancel", response_model=JobDetailView)
def cancel_job(job_id: str, body: JobActionInput, request: Request, user: AdminDep, db: DB):
    """与用户取消使用同一状态机，未知结果不允许运营直接返还预占。"""
    job = require_job(db, job_id, locked=True)
    if job.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "任务状态已变化，请刷新后操作")
    cancel(db, job)
    db.add(Audit(actor_id=user.id, action="job.cancel", resource_id=job.id, summary={"status": job.status}))
    db.commit()
    return detail(request.app, db, job)

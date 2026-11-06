"""Run 查询与取消入口；取消不等同于撤销已发送给供应商的 HTTP 请求。"""

from fastapi import APIRouter
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.security import DB, StaffDep, UserDep
from app.modules.projects.service import require_project

from .models import AgentRun, AgentStep
from .schemas import RunView, StepView

router = APIRouter(tags=["agents"])


@router.get("/api/v1/web/agent-runs/{run_id}", response_model=RunView)
def get_run(run_id: str, user: UserDep, db: DB):
    """只有项目拥有者可读取运行信息。"""
    run = db.get(AgentRun, run_id)
    if run is None:
        raise DomainError("NOT_FOUND", "对话不可访问", 404)
    if run.project_id:
        project = require_project(db, run.project_id, user.id)
        if project.privacy_epoch != run.privacy_epoch:
            raise DomainError("NOT_FOUND", "对话不可访问", 404)
    elif run.owner_user_id != user.id:
        raise DomainError("NOT_FOUND", "对话不可访问", 404)
    return run


@router.post("/api/v1/web/agent-runs/{run_id}/cancel", response_model=RunView)
def cancel_run(run_id: str, user: UserDep, db: DB):
    """立即撤销最终回复提交权，网络进行中也不发布迟到的提案。"""
    run = get_run(run_id, user, db)
    from app.workers.agent_runtime import lock_run

    project, _, run = lock_run(db, run_id)
    if project and project.privacy_epoch != run.privacy_epoch:
        raise DomainError("NOT_FOUND", "对话不可访问", 404)
    if run.status in {"queued", "running"}:
        from app.core.db import now

        run.status, run.stage, run.finished_at = "cancelled", "cancelled", now()
        run.stream_json = None
        for step in db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "running")
        ):
            step.status = "cancelled"
            step.error_code = "AGENT_CANCELLED"
            step.finished_at = now()
    db.commit()
    return run


@router.get("/api/v1/web/agent-runs/{run_id}/steps", response_model=list[StepView])
def run_steps(run_id: str, user: UserDep, db: DB):
    """拥有者诊断步骤，隐私代次复核与Run读取一致。"""
    run = get_run(run_id, user, db)
    return db.scalars(
        select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.seq).limit(32)
    ).all()


@router.get("/api/v1/admin/agent-runs/{run_id}/steps", response_model=list[StepView])
def staff_run_steps(run_id: str, user: StaffDep, db: DB):
    """客服员工只可诊断已请求/接管客服，不开放用户创作上下文。"""
    from app.modules.conversations.support_api import staff_conversation

    run = db.get(AgentRun, run_id)
    if run is None:
        raise DomainError("NOT_FOUND", "运行不存在", 404)
    staff_conversation(db, run.conversation_id, user)
    return db.scalars(
        select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.seq).limit(32)
    ).all()

"""项目与账户删除屏障；不保留通用偏好，也不让迟到任务重建私有内容。"""

from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, UserDep
from app.modules.assets.models import Asset
from app.modules.operations.models import Audit
from app.modules.project_memory.service import scrub_memory

from .models import Project, Subject
from .service import require_project

router = APIRouter(tags=["privacy"])


class DeleteConfirmation(Input):
    """不可逆删除必须是用户的独立明确动作。"""

    confirmed: Literal[True]


def mark_deleted(db, project):
    """只由拥有者锁定项目后调用，访问先阻断，物理文件由维护进程清除。"""
    project.lifecycle, project.title = "deleted", "[已删除项目]"
    project.privacy_epoch += 1
    project.brief_revision += 1
    for subject in db.scalars(select(Subject).where(Subject.project_id == project.id)):
        subject.authorization_state, subject.display_name = "revoked", "[已撤销]"
        subject.authorization_revision += 1
    for asset in db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.status != "deleted")):
        asset.status = "deleting"
    scrub_memory(db, project)


@router.delete("/api/v1/web/projects/{project_id}")
def delete_project(project_id: str, body: DeleteConfirmation, user: UserDep, db: DB):
    """删除整个项目含所有偏好；正在提交的远端成本仍须按原请求核对。"""
    project = require_project(db, project_id, user.id, lock=True)
    mark_deleted(db, project)
    db.add(
        Audit(
            actor_id=user.id, action="project.delete", resource_id=project.id, summary={"cleanup": "pending"}
        )
    )
    db.commit()
    return {"ok": True, "cleanup": "pending"}


@router.delete("/api/v1/web/account")
def delete_account(body: DeleteConfirmation, user: UserDep, db: DB, response: Response):
    """普通账户撤销全部会话和私有项目；受控管理身份不能在此注销。"""
    if user.role != "customer":
        raise DomainError("PERMISSION_DENIED", "管理身份需要受控管理流程", 403)
    projects = db.scalars(
        select(Project)
        .where(Project.owner_user_id == user.id, Project.lifecycle != "deleted")
        .order_by(Project.id)
        .with_for_update()
    )
    for project in projects:
        mark_deleted(db, project)
    from app.modules.agents.models import AgentRun, AgentStep
    from app.modules.conversations.models import Conversation, Message
    from app.modules.conversations.support import cancel_automation

    for conversation in db.scalars(
        select(Conversation).where(Conversation.owner_user_id == user.id).with_for_update()
    ):
        cancel_automation(db, conversation)
        conversation.handoff_status, conversation.assigned_staff_id = "bot", None
        conversation.revision += 1
        for message in db.scalars(select(Message).where(Message.conversation_id == conversation.id)):
            message.text = "[账户删除后已清除]"
            message.proposal_json = message.memory_suggestion_json = message.brief_suggestion_json = None
            message.observations_json = message.citations_json = None
        for run in db.scalars(select(AgentRun).where(AgentRun.conversation_id == conversation.id)):
            run.context_json, run.manifest_json, run.tool_trace_json, run.stream_json = (
                {},
                {"scrubbed": True},
                [],
                None,
            )
            for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)):
                step.manifest_json = {"scrubbed": True}
    from app.integrations.call_logging import scrub_calls

    scrub_calls(db, owner_user_id=user.id)
    user.status, user.display_name, user.login_hash = "deleted", "[已删除账户]", "deleted:" + uid()
    user.session_version += 1
    db.commit()
    response.delete_cookie("yx_web", path="/api/v1/web")
    return {"ok": True, "cleanup": "pending"}

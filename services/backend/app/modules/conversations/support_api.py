"""独立客服与员工接管API；默认无照片访问能力，不能接管创作会话。"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select

from app.core.db import uid
from app.core.errors import DomainError
from app.core.security import DB, StaffDep, UserDep
from app.modules.projects.service import require_project

from .models import Conversation, Message
from .support import handoff, open_support, own_conversation, send_support, support_snapshot
from .support_schemas import (
    ConversationEntry,
    HandoffInput,
    OpenSupport,
    StaffReply,
    SupportEntry,
    SupportSend,
    SupportView,
)

router = APIRouter(tags=["support"])


@router.get("/api/v1/web/conversations", response_model=list[ConversationEntry])
def list_conversations(user: UserDep, db: DB):
    """拥有者会话列表；项目归属/状态再次核对，不泄漏其他用户或已撤销材料。"""
    from app.modules.projects.models import Project

    rows = db.scalars(
        select(Conversation)
        .where(Conversation.owner_user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .limit(100)
    )
    result = []
    for conv in rows:
        if conv.bound_project_id:
            project = db.get(Project, conv.bound_project_id)
            if not project or project.owner_user_id != user.id or project.lifecycle != "active":
                continue
        result.append(
            {
                "id": conv.id,
                "project_id": conv.bound_project_id,
                "entry_mode": conv.entry_mode,
                "handoff_status": conv.handoff_status,
                "revision": conv.revision,
                "created_at": conv.created_at,
            }
        )
    return result


@router.post("/api/v1/web/conversations", response_model=SupportView)
def open_conversation(body: OpenSupport, user: UserDep, db: DB, request: Request):
    """显式打开独立客服；有项目时也与创作会话分开。"""
    conv = open_support(request.app, db, user, body.project_id)
    project = require_project(db, body.project_id, user.id) if body.project_id else None
    return support_snapshot(request.app, db, conv, project)


@router.get("/api/v1/web/conversations/{conversation_id}/messages", response_model=SupportView)
@router.get("/api/v1/web/conversations/{conversation_id}", response_model=SupportView)
def read_conversation(
    conversation_id: str,
    user: UserDep,
    db: DB,
    request: Request,
    cursor: str | None = Query(default=None, max_length=2048),
):
    """客服快照与旧页恢复，重新校验项目拥有者/隐私。"""
    conv, project = own_conversation(db, conversation_id, user.id)
    return support_snapshot(request.app, db, conv, project, cursor)


@router.post(
    "/api/v1/web/conversations/{conversation_id}/messages", response_model=SupportView, status_code=202
)
def send(conversation_id: str, body: SupportSend, user: UserDep, db: DB, request: Request):
    """机器人排队或人工期间仅存消息，不越权生成提案。"""
    return send_support(request.app, db, user, conversation_id, body)


@router.post("/api/v1/web/conversations/{conversation_id}/handoff", response_model=SupportView)
def request_handoff(conversation_id: str, body: HandoffInput, user: UserDep, db: DB, request: Request):
    """用户留言请求人工，实际领取前机器人继续响应。"""
    conv, project = own_conversation(db, conversation_id, user.id, lock=True)
    handoff(db, user, conv, body.expected_revision, "request")
    return support_snapshot(request.app, db, conv, project)


@router.post("/api/v1/web/conversations/{conversation_id}/handoff/withdraw", response_model=SupportView)
def withdraw_handoff(conversation_id: str, body: HandoffInput, user: UserDep, db: DB, request: Request):
    """拥有者撤回留言或退出人工，旧员工窗口失去回复和读取权限。"""
    conv, project = own_conversation(db, conversation_id, user.id, lock=True)
    handoff(db, user, conv, body.expected_revision, "withdraw")
    return support_snapshot(request.app, db, conv, project)


def staff_conversation(db, conversation_id, user, *, lock=False):
    """员工只读待领取或本人已领取的客服；不能借此查看创作聊天。"""
    conv = db.get(Conversation, conversation_id)
    if not conv or conv.entry_mode != "support_only":
        raise DomainError("NOT_FOUND", "客服会话不可访问", 404)
    if not (
        conv.handoff_status == "requested"
        or conv.handoff_status == "human"
        and conv.assigned_staff_id == user.id
    ):
        raise DomainError("PERMISSION_DENIED", "仅可访问待领取或本人接管的客服会话", 403)
    return own_conversation(db, conversation_id, conv.owner_user_id, lock=lock)


@router.get("/api/v1/admin/support", response_model=list[SupportEntry])
def support_list(user: StaffDep, db: DB):
    """有界待办列表，不展示普通用户项目或未请求人工的会话内容。"""
    rows = db.scalars(
        select(Conversation)
        .where(
            Conversation.entry_mode == "support_only",
            or_(
                Conversation.handoff_status == "requested",
                (Conversation.handoff_status == "human") & (Conversation.assigned_staff_id == user.id),
            ),
        )
        .order_by(Conversation.created_at)
        .limit(100)
    )
    return [
        {
            "id": c.id,
            "project_id": c.bound_project_id,
            "revision": c.revision,
            "handoff_status": c.handoff_status,
            "assigned_staff_id": c.assigned_staff_id,
            "created_at": c.created_at,
        }
        for c in rows
    ]


@router.get("/api/v1/admin/support/{conversation_id}", response_model=SupportView)
def staff_snapshot(
    conversation_id: str,
    user: StaffDep,
    db: DB,
    request: Request,
    cursor: str | None = Query(default=None, max_length=2048),
):
    """授权客服历史没有创作草稿/参考图，仅公开消息与Run摘要。"""
    conv, project = staff_conversation(db, conversation_id, user)
    return support_snapshot(request.app, db, conv, project, cursor)


@router.post("/api/v1/admin/support/{conversation_id}/claim", response_model=SupportView)
def claim(conversation_id: str, body: HandoffInput, user: StaffDep, db: DB, request: Request):
    """按项目→会话锁序，两个员工只能一个领取成功。"""
    conv, project = staff_conversation(db, conversation_id, user, lock=True)
    handoff(db, user, conv, body.expected_revision, "claim")
    return support_snapshot(request.app, db, conv, project)


@router.post("/api/v1/admin/support/{conversation_id}/release", response_model=SupportView)
def release(conversation_id: str, body: HandoffInput, user: StaffDep, db: DB, request: Request):
    """交还仅启用下一条消息，绝不重放人工期间消息。"""
    conv, project = staff_conversation(db, conversation_id, user, lock=True)
    handoff(db, user, conv, body.expected_revision, "release")
    return support_snapshot(request.app, db, conv, project)


@router.post("/api/v1/admin/support/{conversation_id}/messages", response_model=SupportView)
def staff_message(conversation_id: str, body: StaffReply, user: StaffDep, db: DB, request: Request):
    """只有已领取员工可回复，正文防重与操作人一起持久化。"""
    conv, project = staff_conversation(db, conversation_id, user, lock=True)
    existing = db.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.client_message_id == body.client_message_id
        )
    )
    if existing:
        if existing.actor_id != user.id or existing.text != body.text:
            raise DomainError("IDEMPOTENCY_CONFLICT", "相同消息键内容已变化")
        return support_snapshot(request.app, db, conv, project)
    if conv.handoff_status != "human" or conv.assigned_staff_id != user.id:
        raise DomainError("PERMISSION_DENIED", "请先领取会话", 403)
    if conv.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "客服状态已变化")
    if body.expected_privacy_epoch != (project.privacy_epoch if project else 0):
        raise DomainError("AUTHORIZATION_CHANGED", "项目授权已变化，请重新查看后回复")
    db.add(
        Message(
            conversation_id=conv.id,
            run_id=uid(),
            seq=conv.next_seq,
            role="staff",
            actor_id=user.id,
            client_message_id=body.client_message_id,
            text=body.text,
            privacy_epoch=project.privacy_epoch if project else 0,
        )
    )
    conv.next_seq += 1
    db.commit()
    return support_snapshot(request.app, db, conv, project)


@router.get(
    "/api/v1/web/conversations/{conversation_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "客服原生增量与已提交状态通知；重连读取权威快照",
        }
    },
)
async def support_events(conversation_id: str, request: Request):
    """客服原生流/人工消息同一SSE，断线只重同步，不重发模型或人工消息。"""
    from fastapi.responses import StreamingResponse
    from starlette.concurrency import run_in_threadpool

    from .events import event_stream
    from .support_events import read_stamp

    if not request.app.state.config["conversation_stream"]["enabled"]:
        raise DomainError("STREAM_DISABLED", "实时连接未开放", 503)
    initial = await run_in_threadpool(read_stamp, request, conversation_id)
    return StreamingResponse(
        event_stream(request, conversation_id, initial, reader=read_stamp),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

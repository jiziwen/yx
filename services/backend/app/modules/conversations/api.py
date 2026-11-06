"""项目内聊天快照与防重消息提交；读取不创建会话或调用 LLM。"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.core.errors import DomainError
from app.core.security import DB, UserDep
from app.modules.agents.schemas import ConversationView, MessagePage, RunView, SendMessage
from app.modules.agents.service import send_message, snapshot
from app.modules.projects.service import require_project

from .events import event_stream, read_stamp
from .history import message_page
from .support_api import router as support_router

router = APIRouter(tags=["conversations"])
router.include_router(support_router)


@router.get("/api/v1/web/projects/{project_id}/conversation/history", response_model=MessagePage)
def history(
    project_id: str,
    user: UserDep,
    db: DB,
    request: Request,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
):
    """用户可翻阅旧消息，默认20条；读取不触发 LLM 或修改长期记忆。"""
    return message_page(request.app, db, require_project(db, project_id, user.id), cursor=cursor, limit=limit)


@router.get(
    "/api/v1/web/projects/{project_id}/conversation/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "授权范围内的失效通知；收到 ready 后读取会话快照",
        }
    },
)
async def events(project_id: str, request: Request):
    """Cookie 鉴权后订阅；禁止把请求级 DB 依赖带入长连接。"""
    initial = await run_in_threadpool(read_stamp, request, project_id)
    if not request.app.state.config["conversation_stream"]["enabled"]:
        raise DomainError("STREAM_DISABLED", "实时连接暂不可用，请通过快照恢复", 503)
    return StreamingResponse(
        event_stream(request, project_id, initial),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/web/projects/{project_id}/conversation", response_model=ConversationView)
def conversation(project_id: str, user: UserDep, db: DB, request: Request):
    """持久化快照供断线和刷新恢复，始终重新校验项目拥有者。"""
    project = require_project(db, project_id, user.id)
    return snapshot(request.app, db, project)


@router.post("/api/v1/web/projects/{project_id}/messages", response_model=RunView, status_code=202)
def message(project_id: str, body: SendMessage, user: UserDep, db: DB, request: Request):
    """只入队一轮 Agent，不创建方案、审批、媒体任务或权益流水。"""
    return send_message(request.app, db, user, project_id, body)

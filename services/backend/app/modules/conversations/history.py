"""当前项目消息分页与关键词只读检索；遗忘截止线只限制模型读取，不删用户可见历史。"""

from datetime import datetime

from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import Field
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.views import View
from app.modules.agents.models import AgentRun
from app.modules.conversations.models import Conversation, Message
from app.modules.project_memory.models import ProjectMemory


def cutoff_at(db, project_id):
    """统一最近历史注入与检索的遗忘边界，清空/替换已确认要求后不能绕过。"""
    row = db.get(ProjectMemory, project_id)
    return row.history_cutoff_at if row else None


def cursor_codec(app):
    """游标签名隔离于登录 Cookie，不接受裸序号或跨项目/代次游标。"""
    return URLSafeTimedSerializer(app.state.settings.session_secret, salt="yingxu-conversation-history-v1")


def message_page(app, db, project, *, cursor=None, limit=20):
    """稳定 before_seq 翻页；新增消息不会使旧页重复或漏项，返回升序消息。"""
    before = None
    if cursor:
        try:
            value = cursor_codec(app).loads(cursor, max_age=3600)
            if (
                value["project"] != project.id
                or value["epoch"] != project.privacy_epoch
                or type(value["before"]) is not int
                or value["before"] < 1
            ):
                raise ValueError("scope")
            before = value["before"]
        except (BadData, KeyError, ValueError, TypeError) as exc:
            raise DomainError("HISTORY_CURSOR_INVALID", "历史游标已失效，请重新同步对话", 409) from exc
    conversation = db.scalar(select(Conversation).where(Conversation.project_id == project.id))
    query = select(Message).where(
        Message.conversation_id == (conversation.id if conversation else ""),
        Message.privacy_epoch == project.privacy_epoch,
    )
    if before is not None:
        query = query.where(Message.seq < before)
    rows = list(db.scalars(query.order_by(Message.seq.desc()).limit(limit + 1)))
    items = rows[:limit][::-1]
    next_cursor = (
        cursor_codec(app).dumps(
            {"project": project.id, "epoch": project.privacy_epoch, "before": items[0].seq}
        )
        if len(rows) > limit
        else None
    )
    run_ids = {item.run_id for item in items}
    runs = (
        list(
            db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.id.in_(run_ids),
                    AgentRun.project_id == project.id,
                    AgentRun.privacy_epoch == project.privacy_epoch,
                )
                .order_by(AgentRun.created_at)
            )
        )
        if run_ids
        else []
    )
    return {"items": items, "runs": runs, "next_cursor": next_cursor, "privacy_epoch": project.privacy_epoch}


class HistoryArguments(Input):
    """只查原文关键词；通配符按字面匹配，身份和项目不能由模型指定。"""

    query: str = Field(min_length=1, max_length=80)
    limit: int = Field(default=3, ge=1, le=4)


class HistoryFact(View):
    """可核对的历史原话，省略提案/工具证据和任何素材数据。"""

    message_id: str
    run_id: str
    seq: int
    role: str
    text: str
    truncated: bool
    created_at: datetime


class HistoryResult(View):
    """历史仅供回溯，不能晋升记忆、还原已删除要求或充当实时业务状态。"""

    query: str
    messages: list[HistoryFact]
    more_available: bool
    history_cutoff_at: datetime | None
    strategy: str = "literal_keyword_v1"


class HistorySearchTool:
    """只读当前项目、成功轮次、当前隐私代次及遗忘截止线之后的消息。"""

    name, version, title = "search_project_history", "1", "查询项目历史原话"
    role, scope, read_only = "creative", "current_project", True
    requires = ("conversations", "project_memory")
    input_model, output_model = HistoryArguments, HistoryResult

    def read(self, app, db, scope, arguments):
        """结果上限四条且每条500字；不将未确认建议或工具 JSON 当成当前事实。"""
        cutoff = cutoff_at(db, scope.project_id)
        query = (
            select(Message)
            .join(AgentRun, Message.run_id == AgentRun.id)
            .where(
                AgentRun.project_id == scope.project_id,
                AgentRun.status == "succeeded",
                AgentRun.privacy_epoch == scope.privacy_epoch,
                Message.privacy_epoch == scope.privacy_epoch,
                Message.role.in_(["user", "assistant"]),
                Message.text.contains(arguments.query, autoescape=True),
            )
        )
        if cutoff:
            query = query.where(AgentRun.created_at >= cutoff)
        rows = list(db.scalars(query.order_by(Message.seq.desc()).limit(arguments.limit + 1)))
        return {
            "query": arguments.query,
            "history_cutoff_at": cutoff,
            "more_available": len(rows) > arguments.limit,
            "messages": [
                {
                    "message_id": item.id,
                    "run_id": item.run_id,
                    "seq": item.seq,
                    "role": item.role,
                    "text": item.text[:500],
                    "truncated": len(item.text) > 500,
                    "created_at": item.created_at,
                }
                for item in rows[: arguments.limit]
            ],
        }

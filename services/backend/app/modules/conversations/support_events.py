"""客服原生回复/人工消息通知复用会话SSE协议，每次采样重新鉴权。"""

from sqlalchemy import func, select

from app.core.security import authenticate
from app.modules.agents.models import AgentRun
from app.modules.agents.service import enabled

from .events import Stamp
from .models import Message
from .support import own_conversation


def read_stamp(request, conversation_id):
    """只保留短事务快照；人工交接版本变化触发重新读取权威状态。"""
    app = request.app
    with app.state.sessions() as db:
        user = authenticate(request, db, "web")
        conv, project = own_conversation(db, conversation_id, user.id)
        epoch = project.privacy_epoch if project else 0
        sequence = (
            db.scalar(
                select(func.max(Message.seq)).where(
                    Message.conversation_id == conv.id, Message.privacy_epoch == epoch
                )
            )
            or 0
        )
        rows = db.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conv.id, AgentRun.privacy_epoch == epoch)
            .order_by(AgentRun.created_at.desc())
            .limit(20)
        )
        runs = {}
        previews = {}
        for run in rows:
            runs[run.id] = (run.status, run.stage, run.calls, run.tool_calls, run.error_code, run.finished_at)
            if run.status == "running" and run.stream_json:
                previews[run.id] = run.stream_json
        return Stamp(
            epoch=epoch,
            project=(conv.revision, conv.handoff_status, enabled(app)),
            conversation_id=conv.id,
            seq=sequence,
            runs=runs,
            previews=previews,
        )

"""跨 Worker 的数据库通知：临时回复按尝试替换，正式消息从权威快照读取。"""

import asyncio
import json
from dataclasses import dataclass, field
from time import monotonic

from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.core.db import now, uid
from app.core.errors import DomainError
from app.core.security import authenticate
from app.modules.agents.models import AgentRun
from app.modules.agents.service import enabled
from app.modules.conversations.models import Conversation, Message
from app.modules.project_memory.service import memory_view
from app.modules.projects.service import require_project


@dataclass(frozen=True)
class Stamp:
    """仅在当前连接内比较；不作为可回放事件或客户端业务版本。"""

    epoch: int
    project: tuple
    conversation_id: str | None
    seq: int
    runs: dict[str, tuple]
    previews: dict[str, dict] = field(default_factory=dict)


def read_stamp(request, project_id: str) -> Stamp:
    """每次重新鉴权，短事务关闭后才等待网络，不长期占用数据库连接。"""
    app = request.app
    with app.state.sessions() as db:
        user = authenticate(request, db, "web")
        project = require_project(db, project_id, user.id)
        conversation = db.scalar(select(Conversation).where(Conversation.project_id == project.id))
        memory = memory_view(app, db, project)
        runs, previews, seq = {}, {}, 0
        if conversation:
            seq = (
                db.scalar(
                    select(func.max(Message.seq)).where(
                        Message.conversation_id == conversation.id,
                        Message.privacy_epoch == project.privacy_epoch,
                    )
                )
                or 0
            )
            rows = db.execute(
                select(
                    AgentRun.id,
                    AgentRun.status,
                    AgentRun.stage,
                    AgentRun.calls,
                    AgentRun.tool_calls,
                    AgentRun.error_code,
                    AgentRun.finished_at,
                    AgentRun.stream_json,
                )
                .where(
                    AgentRun.conversation_id == conversation.id,
                    AgentRun.privacy_epoch == project.privacy_epoch,
                )
                .order_by(AgentRun.created_at.desc())
                .limit(30)
            )
            for row in rows:
                runs[row.id] = tuple(row)[1:-1]
                if row.status == "running" and row.stream_json:
                    previews[row.id] = row.stream_json
        return Stamp(
            epoch=project.privacy_epoch,
            project=(
                project.brief_revision,
                project.lifecycle,
                memory["revision"],
                memory["enabled"],
                enabled(app),
            ),
            conversation_id=conversation.id if conversation else None,
            seq=seq,
            runs=runs,
            previews=previews,
        )


def frame(
    event: str, resource_id: str, *, revision: int | None = None, payload=None, run_id=None, attempt_no=None
) -> str:
    """标准帧；仅临时 reply 可带可见正文，没有原始 JSON/推理/私有素材。"""
    envelope = {
        "schema_version": 1,
        "event_id": uid(),
        "resource_id": resource_id,
        "occurred_at": now().isoformat(),
        "resource_revision": revision,
        "payload": payload or {},
        "run_id": run_id,
        "attempt_no": attempt_no,
    }
    return f"event: {event}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"


def changes(before: Stamp, after: Stamp, project_id: str) -> list[str]:
    """只通知已提交事实的变化；中间阶段可以合并，最终快照不能依赖通知完整性。"""
    events = []
    if before.project != after.project:
        events.append(frame("stream.sync", project_id))
    if before.seq != after.seq or before.conversation_id != after.conversation_id:
        events.append(frame("message.committed", after.conversation_id or project_id, revision=after.seq))
    for run_id, value in after.runs.items():
        if before.runs.get(run_id) != value:
            events.append(frame("run.updated", run_id))
    for run_id in before.previews.keys() | after.previews.keys():
        preview = after.previews.get(run_id)
        if preview != before.previews.get(run_id):
            attempt = after.runs[run_id][2] if run_id in after.runs else before.runs[run_id][2]
            events.append(
                frame(
                    "message.delta",
                    run_id,
                    revision=preview["seq"] if preview else None,
                    run_id=run_id,
                    attempt_no=attempt,
                    payload={
                        "privacy_epoch": after.epoch,
                        "preview": preview,
                        "closed": run_id not in after.runs
                        or after.runs[run_id][0] not in {"queued", "running"},
                    },
                )
            )
    return events


async def event_stream(request, project_id: str, initial: Stamp, reader=None):
    """先建立观察基线再 ready；重连重新同步，不隐含重试任何模型调用。"""
    reader = reader or read_stamp
    config = request.app.state.config["conversation_stream"]
    previous = initial
    started = heartbeat = monotonic()
    yield frame("stream.ready", project_id, payload={"privacy_epoch": initial.epoch})
    # 订阅时已有的片段也发送；新连接不必等待下一次模型输出才恢复当前前缀。
    for run_id, preview in initial.previews.items():
        yield frame(
            "message.delta",
            run_id,
            revision=preview["seq"],
            run_id=run_id,
            attempt_no=preview["attempt_no"],
            payload={"privacy_epoch": initial.epoch, "preview": preview},
        )
    while not await request.is_disconnected():
        active = any(value[0] in {"queued", "running"} for value in previous.runs.values())
        await asyncio.sleep(config["delta_poll_seconds"] if active else config["poll_seconds"])
        try:
            current = await run_in_threadpool(reader, request, project_id)
        except DomainError:
            yield frame("stream.revoked", project_id)
            return
        if current.epoch != initial.epoch:
            yield frame("stream.reset", project_id)
            return
        for event in changes(previous, current, project_id):
            yield event
        previous = current
        elapsed = monotonic()
        if elapsed - heartbeat >= config["heartbeat_seconds"]:
            yield frame("stream.heartbeat", project_id)
            heartbeat = elapsed
        if elapsed - started >= config["max_connection_seconds"]:
            yield frame("stream.reconnect", project_id)
            return

"""客服入口、持久消息及人工接管；同一Agent运行层，无第二套LLM业务实现。"""

from datetime import timedelta

from itsdangerous import BadData
from sqlalchemy import func, select

from app.core.db import now, uid
from app.core.errors import DomainError
from app.modules.agents.context import fingerprint
from app.modules.agents.models import AgentRun, AgentStep
from app.modules.agents.service import ACTIVE, enabled, model_info
from app.modules.media_jobs.governance import lock_gate
from app.modules.operations.models import Audit
from app.modules.projects.models import Project
from app.modules.projects.service import require_project

from .history import cursor_codec
from .models import Conversation, Message


def own_conversation(db, conversation_id, user_id, *, lock=False):
    """用户或Worker只按真实拥有者读取，独立客服不借用任意项目权限。"""
    hint = db.get(Conversation, conversation_id)
    if hint is None or hint.entry_mode != "support_only" or hint.owner_user_id != user_id:
        raise DomainError("NOT_FOUND", "客服会话不可访问", 404)
    project = (
        require_project(db, hint.bound_project_id, user_id, lock=lock) if hint.bound_project_id else None
    )
    query = select(Conversation).where(Conversation.id == conversation_id)
    conv = db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)
    return conv, project


def open_support(app, db, user, project_id):
    """同用户/项目独立客服唯一；没有项目的会话也不自动创建创作项目。"""
    if not app.state.config["features"].get("support_enabled", False):
        raise DomainError("SUPPORT_DISABLED", "客服入口暂未开放", 503)
    if project_id:
        require_project(db, project_id, user.id, lock=True)
    else:
        lock_gate(db, "support-open:" + user.id)
    key = f"support:{user.id}:{project_id or 'account'}"
    conv = db.scalar(select(Conversation).where(Conversation.scope_key == key))
    if not conv:
        conv = Conversation(
            owner_user_id=user.id,
            context_project_id=project_id,
            scope_key=key,
            entry_mode="support_only",
            handoff_status="bot",
            next_seq=1,
            revision=0,
        )
        db.add(conv)
        db.commit()
    return conv


def support_snapshot(app, db, conv, project, cursor=None):
    """签名旧页游标绑定会话/代次，最新状态始终读取权威表。"""
    epoch = project.privacy_epoch if project else 0
    before = None
    if cursor:
        try:
            data = cursor_codec(app).loads(cursor, max_age=3600)
            if data["conversation"] != conv.id or data["epoch"] != epoch or type(data["before"]) is not int:
                raise ValueError("scope")
            before = data["before"]
        except (BadData, KeyError, TypeError, ValueError) as exc:
            raise DomainError("HISTORY_CURSOR_INVALID", "客服历史游标已失效", 409) from exc
    query = select(Message).where(Message.conversation_id == conv.id, Message.privacy_epoch == epoch)
    if before:
        query = query.where(Message.seq < before)
    rows = list(db.scalars(query.order_by(Message.seq.desc()).limit(41)))
    messages = rows[:40][::-1]
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conv.id, AgentRun.privacy_epoch == epoch)
            .order_by(AgentRun.created_at.desc())
            .limit(20)
        )
    )[::-1]
    _, model, development = model_info(app)
    return {
        "id": conv.id,
        "project_id": conv.bound_project_id,
        "revision": conv.revision,
        "privacy_epoch": epoch,
        "handoff_status": conv.handoff_status,
        "assigned_staff_id": conv.assigned_staff_id,
        "messages": messages,
        "runs": runs,
        "older_cursor": cursor_codec(app).dumps(
            {"conversation": conv.id, "epoch": epoch, "before": messages[0].seq}
        )
        if len(rows) > 40
        else None,
        "enabled": enabled(app) and app.state.config["features"].get("support_enabled", False),
        "model": model,
        "development_sample": development,
    }


def build_support_context(app, db, conv, project, text):
    """客服不读取照片/人物/草稿/长期创作偏好，只保留必要项目事实和公开知识。"""
    budget = app.state.config["agent"]
    epoch = project.privacy_epoch if project else 0
    descriptors = app.state.agent_tools.descriptors(
        {m.id for m in app.state.modules}, role="support", has_project=bool(project)
    )
    facts = {
        "role": "support",
        "project": {"kind": project.kind} if project else None,
        "read_tools": descriptors,
        "memory": {
            "enabled": False,
            "revision": 0,
            "requirements": [],
            "fields": {},
            "field_definitions": [],
        },
        "handoff_available": True,
    }
    history = []
    included = []
    messages = (
        list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.privacy_epoch == epoch)
                .order_by(Message.seq.desc())
                .limit(budget["history_turns"] * 2)
            )
        )[::-1]
        if conv
        else []
    )
    used = len(text) + len(__import__("json").dumps(facts, ensure_ascii=False))
    for message in reversed(messages):
        if used + len(message.text) > budget["max_context_chars"] - budget["tool_context_reserve"]:
            break
        history.insert(
            0, {"role": "user" if message.role == "user" else "assistant", "content": message.text}
        )
        included.insert(0, message.id)
        used += len(message.text)
    return {"facts": facts, "history": history, "text": text}, {
        "strategy": "support-public-v1",
        "selected_asset_ids": [],
        "memory_enabled": False,
        "history_message_ids": included,
        "input_chars": used,
        "input_token_upper_estimate": used * 3,
        "context_hash": fingerprint({"facts": facts, "history": history, "text": text}),
        "handoff_revision": conv.revision if conv else 0,
    }


def send_support(app, db, user, conversation_id, body):
    """人工期间仅保存用户消息；交还后只有下一条新消息会启动模型。"""
    conv, project = own_conversation(db, conversation_id, user.id, lock=True)
    existing = db.scalar(
        select(Message).where(
            Message.conversation_id == conv.id, Message.client_message_id == body.client_message_id
        )
    )
    epoch = project.privacy_epoch if project else 0
    if existing:
        if existing.text != body.text or existing.privacy_epoch != epoch:
            raise DomainError("IDEMPOTENCY_CONFLICT", "重试消息内容或授权已变化")
        return support_snapshot(app, db, conv, project)
    if conv.revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "客服接管状态已变化，请刷新")
    if epoch != body.expected_privacy_epoch:
        raise DomainError("AUTHORIZATION_CHANGED", "项目授权已变化，请刷新")
    if not enabled(app) or not app.state.config["features"].get("support_enabled", False):
        raise DomainError("SUPPORT_DISABLED", "客服暂不可用", 503)
    run_id = uid()
    if conv.handoff_status in {"bot", "requested"}:
        lock_gate(db, "agent-admission")
        if db.scalar(
            select(AgentRun).where(AgentRun.conversation_id == conv.id, AgentRun.status.in_(ACTIVE))
        ):
            raise DomainError("AGENT_BUSY", "正在处理上一条消息")
        limits = app.state.config["agent"]
        total = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.status.in_(ACTIVE)))
        own = db.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.owner_user_id == user.id, AgentRun.status.in_(ACTIVE))
        )
        if total >= limits["max_pending"] or own >= limits["max_user_pending"]:
            raise DomainError("AGENT_CAPACITY", "当前对话较多，请稍后再试", 429)
        context, manifest = build_support_context(app, db, conv, project, body.text)
        policy, model, development = model_info(app)
        from app.modules.agents.releases import release_snapshot

        db.add(
            AgentRun(
                id=run_id,
                conversation_id=conv.id,
                project_id=project.id if project else None,
                owner_user_id=user.id,
                primary_role="support",
                client_message_id=body.client_message_id,
                request_hash=fingerprint(body.model_dump()),
                brief_revision=project.brief_revision if project else 0,
                privacy_epoch=epoch,
                context_json=context,
                manifest_json=manifest,
                policy_json=policy,
                budget_json=limits,
                release_json=release_snapshot(app, policy),
                model=model,
                development_sample=development,
                memory_revision=0,
                account_scope=app.state.gateway.definitions[policy["provider_id"]]
                .get("runtime", {})
                .get("account_scope")
                or policy["provider_id"],
                deadline_at=now() + timedelta(seconds=limits["deadline_seconds"]),
            )
        )
        db.flush()
    db.add(
        Message(
            conversation_id=conv.id,
            run_id=run_id,
            client_message_id=body.client_message_id,
            seq=conv.next_seq,
            role="user",
            text=body.text,
            privacy_epoch=epoch,
        )
    )
    conv.next_seq += 1
    db.commit()
    return support_snapshot(app, db, conv, project)


def cancel_automation(db, conv):
    """人工领取立即撤销最终提交权；远端槽仍由既有call_until保留。"""
    for run in db.scalars(
        select(AgentRun)
        .where(AgentRun.conversation_id == conv.id, AgentRun.status.in_(ACTIVE))
        .with_for_update()
    ):
        run.status = "cancelled"
        run.stage = "cancelled"
        run.error_code = "HUMAN_HANDOFF"
        run.finished_at = now()
        run.stream_json = None
        for step in db.scalars(
            select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "running")
        ):
            step.status = "cancelled"
            step.finished_at = now()
            step.error_code = "HUMAN_HANDOFF"


def handoff(db, actor, conv, expected_revision, action):
    """状态/员工所有权/版本原子校验，与审计及自动回复取消一起提交。"""
    if conv.revision != expected_revision:
        raise DomainError("REVISION_CONFLICT", "客服状态已变化，请刷新")
    if action == "request":
        if conv.handoff_status != "bot":
            return conv
        conv.handoff_status = "requested"
    elif action == "claim":
        if conv.handoff_status != "requested":
            raise DomainError("SUPPORT_ALREADY_CLAIMED", "会话已被领取或已交还")
        conv.handoff_status = "human"
        conv.assigned_staff_id = actor.id
        cancel_automation(db, conv)
    elif action == "withdraw":
        if conv.owner_user_id != actor.id:
            raise DomainError("PERMISSION_DENIED", "只有会话拥有者可撤回", 403)
        conv.handoff_status = "bot"
        conv.assigned_staff_id = None
    elif action == "release":
        if conv.handoff_status != "human" or conv.assigned_staff_id != actor.id:
            raise DomainError("PERMISSION_DENIED", "只有当前接管员工可交还", 403)
        conv.handoff_status = "bot"
        conv.assigned_staff_id = None
    conv.revision += 1
    db.add(
        Audit(
            actor_id=actor.id,
            action="support." + action,
            resource_id=conv.id,
            summary={"revision": conv.revision},
        )
    )
    db.commit()
    return conv


def scrub_support_messages(app):
    """没有AgentRun的人工期间消息也受项目隐私清理，不遗漏员工回复。"""
    from app.workers.runtime import begin_write

    with app.state.sessions() as db:
        ids = list(
            db.scalars(
                select(Conversation.id)
                .join(Project, Project.id == Conversation.context_project_id)
                .join(Message, Message.conversation_id == Conversation.id)
                .where(
                    Conversation.entry_mode == "support_only",
                    Message.privacy_epoch != Project.privacy_epoch,
                    Message.text != "[授权变化后已清除]",
                )
                .distinct()
            )
        )
    for conversation_id in ids:
        with app.state.sessions() as db:
            begin_write(db)
            hint = db.get(Conversation, conversation_id)
            conv, project = own_conversation(db, conversation_id, hint.owner_user_id, lock=True)
            for message in db.scalars(
                select(Message).where(
                    Message.conversation_id == conv.id, Message.privacy_epoch != project.privacy_epoch
                )
            ):
                message.text = "[授权变化后已清除]"
                message.proposal_json = None
                message.memory_suggestion_json = None
                message.brief_suggestion_json = None
                message.observations_json = None
                message.citations_json = None
            db.commit()

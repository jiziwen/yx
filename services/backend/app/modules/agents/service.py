"""会话入队和公开状态；所有业务对象均由登录身份与项目绑定。"""

from datetime import timedelta

from sqlalchemy import func, or_, select

from app.core.db import now, uid
from app.core.errors import DomainError
from app.modules.conversations.history import message_page
from app.modules.conversations.models import Conversation, Message
from app.modules.media_jobs.governance import lock_gate
from app.modules.project_memory.service import memory_view
from app.modules.projects.models import Project
from app.modules.projects.service import require_project

from .context import build_context, fingerprint
from .models import AgentRun

ACTIVE = ("queued", "running")


def enabled(app):
    """模块开关与功能开关共同控制；停用后也不再启动新调用。"""
    return app.state.config["features"].get("chat_enabled", False) and {"agents", "conversations"}.issubset(
        {module.id for module in app.state.modules}
    )


def model_info(app, kind="llm"):
    """当前模型来自网关发布版本；开发插件必须明确标记。"""
    policy = app.state.gateway.snapshot(kind)
    definition = app.state.gateway.definitions[policy["provider_id"]]
    return (
        policy,
        definition.get("options", {}).get("model", policy["provider_id"]),
        definition.get("development_only", False),
    )


def snapshot(app, db, project):
    """当前隐私代次最多最近 60 条消息；旧代次内容立即不可见。"""
    conversation = db.scalar(select(Conversation).where(Conversation.project_id == project.id))
    _, model, development = model_info(app)
    page = message_page(app, db, project, limit=60)
    messages, runs = page["items"], []
    if conversation:
        runs = list(
            db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.conversation_id == conversation.id,
                    AgentRun.privacy_epoch == project.privacy_epoch,
                )
                .order_by(AgentRun.created_at.desc())
                .limit(30)
            )
        )[::-1]
    runs = sorted({run.id: run for run in [*page["runs"], *runs]}.values(), key=lambda run: run.created_at)
    return {
        "id": conversation.id if conversation else None,
        "project_id": project.id,
        "privacy_epoch": project.privacy_epoch,
        "messages": messages,
        "runs": runs,
        "model": model,
        "development_sample": development,
        "enabled": enabled(app),
        "memory": memory_view(app, db, project),
        "older_cursor": page["next_cursor"],
    }


def send_message(app, db, user, project_id, body):
    """短事务内按项目→会话→容量锁入队；同键同正文只写入一次。"""
    project = require_project(db, project_id, user.id, writable=True)
    conversation = db.scalar(
        select(Conversation).where(Conversation.project_id == project.id).with_for_update()
    )
    digest = fingerprint(body.model_dump())
    if conversation:
        existing = db.scalar(
            select(AgentRun).where(
                AgentRun.conversation_id == conversation.id,
                AgentRun.client_message_id == body.client_message_id,
            )
        )
        if existing:
            if existing.request_hash != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "重试消息内容已变化，请重新发送")
            if existing.privacy_epoch != project.privacy_epoch:
                raise DomainError("AUTHORIZATION_CHANGED", "项目授权已变化，请重新发送")
            return existing
    if not enabled(app):
        raise DomainError("CHAT_DISABLED", "创作对话当前未开放，请使用提案表单", 503)
    if body.expected_revision != project.brief_revision:
        raise DomainError("REVISION_CONFLICT", "项目资料已变化，请刷新后再发送")
    if (
        body.expected_memory_revision is not None
        and body.expected_memory_revision != memory_view(app, db, project)["revision"]
    ):
        raise DomainError("MEMORY_CHANGED", "项目记忆已更新，请重新查看后发送")
    lock_gate(db, "agent-admission")
    active = select(AgentRun).where(AgentRun.status.in_(ACTIVE))
    if conversation and db.scalar(active.where(AgentRun.conversation_id == conversation.id)):
        raise DomainError("AGENT_BUSY", "摄影师正在处理上一条消息，请稍候")
    limits = app.state.config["agent"]
    total = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.status.in_(ACTIVE)))
    own = db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .outerjoin(Project, Project.id == AgentRun.project_id)
        .where(
            or_(Project.owner_user_id == user.id, AgentRun.owner_user_id == user.id),
            AgentRun.status.in_(ACTIVE),
        )
    )
    if total >= limits["max_pending"] or own >= limits["max_user_pending"]:
        raise DomainError("AGENT_CAPACITY", "待处理对话较多，请稍后再发送", 429)
    context, manifest = build_context(app, db, project, conversation, body)
    from .vision import prepare

    kind = prepare(app, db, project, body, context, manifest)
    policy, model, development = model_info(app, kind)
    definition = app.state.gateway.definitions[policy["provider_id"]]
    if conversation is None:
        conversation = Conversation(
            id=uid(),
            project_id=project.id,
            owner_user_id=user.id,
            context_project_id=project.id,
            scope_key=f"project:{project.id}:auto",
            next_seq=1,
        )
        db.add(conversation)
        db.flush()
    from .releases import release_snapshot

    run = AgentRun(
        id=uid(),
        conversation_id=conversation.id,
        project_id=project.id,
        owner_user_id=user.id,
        primary_role=context["facts"].get("role", "creative"),
        release_json=release_snapshot(app, policy),
        client_message_id=body.client_message_id,
        request_hash=digest,
        brief_revision=project.brief_revision,
        privacy_epoch=project.privacy_epoch,
        context_json=context,
        manifest_json=manifest,
        policy_json=policy,
        budget_json=limits,
        model=model,
        development_sample=development,
        memory_revision=context["facts"]["memory"]["revision"],
        account_scope=definition.get("runtime", {}).get("account_scope") or policy["provider_id"],
        deadline_at=now() + timedelta(seconds=limits["deadline_seconds"]),
    )
    db.add(run)
    db.flush()
    db.add(
        Message(
            conversation_id=conversation.id,
            run_id=run.id,
            seq=conversation.next_seq,
            role="user",
            text=body.text,
            privacy_epoch=project.privacy_epoch,
        )
    )
    conversation.next_seq += 1
    db.commit()
    return run

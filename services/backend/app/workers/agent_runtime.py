"""独立 Agent Worker：持久化预算、调用租约、取消与最终原子提交。"""

from datetime import timedelta

from sqlalchemy import select

from app.core.db import now, uid
from app.core.errors import DomainError
from app.core.plugins import load_symbol
from app.integrations.contracts import LLMResult, ProviderFailure, StreamingLLMProvider
from app.modules.agents.models import AgentRun, AgentStep
from app.modules.agents.service import enabled
from app.modules.agents.steps import end_step, start_step
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible
from app.modules.conversations.models import Conversation, Message
from app.modules.identity.models import User
from app.modules.media_jobs.governance import acquire_submission, aware, record_channel_result
from app.modules.project_memory.models import ProjectMemory
from app.modules.project_memory.service import memory_view, scrub_memory
from app.modules.projects.models import Project

from .runtime import begin_write


def lock_run(db, run_id):
    """统一项目→会话→Run 锁序，避免取消、入队与提交形成反向锁。"""
    hint = db.get(AgentRun, run_id)
    if hint is None:
        return None, None, None
    project = db.scalar(
        select(Project)
        .where(Project.id == hint.project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    conversation = db.scalar(
        select(Conversation)
        .where(Conversation.id == hint.conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return project, conversation, run


def valid_inputs(db, project, run, app=None):
    """提交前再次校验账户、项目、需求、隐私、接管及冻结Release代码。"""
    conversation = db.get(Conversation, run.conversation_id)
    user = db.get(User, run.owner_user_id or (project.owner_user_id if project else None))
    if user is None or user.status != "active" or (project and project.lifecycle != "active"):
        raise DomainError("PROJECT_UNAVAILABLE", "项目或账户当前不可用")
    if conversation.entry_mode == "support_only" and (conversation.handoff_status == "human"):
        raise DomainError("HUMAN_HANDOFF", "会话已由人工接管")
    if project is None:
        if conversation.entry_mode != "support_only" or run.primary_role != "support":
            raise DomainError("PROJECT_UNAVAILABLE", "当前会话不能创作")
    else:
        if project.privacy_epoch != run.privacy_epoch:
            raise DomainError("AUTHORIZATION_CHANGED", "人物或素材授权已变化")
        if project.brief_revision != run.brief_revision:
            raise DomainError("REVISION_CONFLICT", "项目资料已变化，请重新发送")
        if run.manifest_json.get("memory_enabled"):
            row = db.get(ProjectMemory, project.id)
            if (row.revision if row else 0) != run.memory_revision:
                raise DomainError("MEMORY_CHANGED", "项目记忆已更新，请基于确认后的要求重新整理")
            if app and not memory_view(app, db, project)["enabled"]:
                raise DomainError("MEMORY_DISABLED", "项目记忆已停用，请重新整理")
            if (
                app
                and run.manifest_json.get("structured_memory")
                and run.budget_json.get("brief_fields") != app.state.config["agent"]["brief_fields"]
            ):
                raise DomainError("MEMORY_CONFIG_CHANGED", "需求卡配置已更新，请重新整理")
        for asset_id in run.manifest_json["selected_asset_ids"]:
            asset = db.get(Asset, asset_id)
            if asset is None or asset.project_id != project.id:
                raise DomainError("INPUT_CHANGED", "素材不可访问")
            assert_accessible(db, asset)
    if app and run.release_json:
        from app.modules.agents.releases import release_snapshot

        current = release_snapshot(app, run.policy_json, agent_config=run.budget_json)
        if run.release_json.get("runtime_catalog_digest") != current.get("runtime_catalog_digest"):
            raise DomainError("CATALOG_CHANGED", "主题素材已更新，请基于最新目录重新整理")
        if current["release_digest"] != run.release_json.get("release_digest"):
            raise DomainError("AGENT_RELEASE_CHANGED", "Agent代码或知识配置已更新，请重新发送")


def finish_failed(app, run_id, token, code):
    """错误只记录稳定分类；不把供应商正文当作助手回复。"""
    with app.state.sessions() as db:
        begin_write(db)
        _, _, run = lock_run(db, run_id)
        if run and run.lease_token == token:
            run.call_until = None
            run.stream_json = None
            if run.status == "running":
                run.status, run.stage, run.error_code, run.finished_at = "failed", "failed", code, now()
            for step in db.scalars(
                select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "running")
            ):
                end_step(db, step.id, error=code)
        db.commit()


def process_run(app, run_id):
    """重复投递仅 queued 可领取；网络在事务外执行，迟到输出没有提交权。"""
    with app.state.sessions() as db:
        begin_write(db)
        project, _, run = lock_run(db, run_id)
        if run is None or run.status != "queued":
            return False
        if not enabled(app):
            run.status, run.stage, run.error_code, run.finished_at = (
                "failed",
                "failed",
                "CHAT_DISABLED",
                now(),
            )
            db.commit()
            return False
        token = uid()
        run.lease_token, run.status, run.stage = token, "running", "reading_context"
        routed = start_step(
            db,
            run,
            "routing",
            run.primary_role,
            {
                "release_digest": run.release_json.get("release_digest"),
                "context_hash": run.manifest_json.get("context_hash"),
                "source_ids": run.manifest_json.get(
                    "history_run_ids", run.manifest_json.get("history_message_ids", [])
                ),
            },
        )
        end_step(db, routed.id)
        db.commit()
        context, budget, policy = run.context_json, run.budget_json, run.policy_json
        call_context = {
            "run_id": run_id,
            "project_id": run.project_id,
            "owner_user_id": run.owner_user_id or (project.owner_user_id if project else None),
            "privacy_epoch": run.privacy_epoch,
        }

    def progress(stage):
        """只展示实际已开始的阶段；每步都复核取消和总截止时间。"""
        with app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, run_id)
            if run.status != "running" or run.lease_token != token:
                raise ProviderFailure("AGENT_CANCELLED")
            if aware(run.deadline_at) <= now():
                raise ProviderFailure("AGENT_TIMEOUT")
            if not enabled(app):
                raise ProviderFailure("CHAT_DISABLED")
            valid_inputs(db, project, run, app)
            if stage in {"contract_valid", "contract_invalid"}:
                checked = start_step(db, run, "validation", "model_contract", {"attempt_no": run.calls})
                end_step(
                    db, checked.id, error="AGENT_INVALID_OUTPUT" if stage == "contract_invalid" else None
                )
                db.commit()
                return
            run.stage = stage
            if stage in {"repairing", "understanding", "reading_results", "querying_tools"}:
                run.stream_json = None
            db.commit()

    def invoke(messages):
        """调用次数先落库；不明网络结果、进程退出或取消均不透明重发。"""
        from evals.m25_runtime import check as check_experiment

        check_experiment(app.state.settings, paid=True)
        app.state.gateway.refresh()
        kind = app.state.gateway.definitions[policy["provider_id"]]["kind"]
        if app.state.gateway.snapshot(kind, policy["provider_id"]) != policy:
            raise ProviderFailure("PROVIDER_CONFIG_CHANGED")
        provider = app.state.gateway.get(kind, policy["provider_id"], audit_context=call_context)
        runtime = app.state.gateway.definitions[policy["provider_id"]].get("runtime", {})
        from app.modules.agents.graph import SYSTEM

        size = sum(len(message.get("content", "")) for message in messages)
        reserve = (
            app.state.gateway.definitions[policy["provider_id"]].get("options", {}).get("max_tokens", 2000)
        )
        if (
            size > budget["max_context_chars"] + len(SYSTEM) + 512
            or size * 3 + reserve + 1024 > budget["context_window_tokens"]
        ):
            raise ProviderFailure("AGENT_CONTEXT_LIMIT")
        with app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, run_id)
            if run.status != "running" or run.lease_token != token:
                raise ProviderFailure("AGENT_CANCELLED")
            valid_inputs(db, project, run, app)
            remaining = (aware(run.deadline_at) - now()).total_seconds()
            if remaining <= 1 or run.calls >= budget["max_calls"]:
                raise ProviderFailure("AGENT_BUDGET_EXCEEDED")
            if not acquire_submission(db, policy["provider_id"], runtime):
                raise ProviderFailure("AGENT_CHANNEL_BUSY")
            from app.modules.agents.vision import hydrate

            outbound = hydrate(app, db, run, messages)
            run.calls += 1
            from app.modules.agents.context import fingerprint

            model_step = start_step(
                db,
                run,
                "model",
                run.model,
                {
                    "attempt_no": run.calls,
                    "input_hash": fingerprint(messages),
                    "input_chars": size,
                    "input_token_upper_estimate": size * 3,
                    "output_token_reserve": reserve,
                    "tool_source_ids": [item["id"] for item in run.tool_trace_json],
                    "knowledge_source_ids": [
                        e["chunk_id"]
                        for item in run.tool_trace_json
                        if item["name"] == "search_knowledge"
                        for e in (item.get("data") or {}).get("evidence", [])
                    ],
                    "context_source_ids": run.manifest_json.get(
                        "history_run_ids", run.manifest_json.get("history_message_ids", [])
                    ),
                    "release_digest": run.release_json.get("release_digest"),
                },
            )
            model_step_id = model_step.id
            attempt_no = run.calls
            run.stream_json = None
            # 即使取消或 Worker 崩溃，也要等此调用期限后再释放远端并发槽。
            call_timeout = min(
                remaining, budget.get("request_timeout_seconds", getattr(provider, "timeout", 60))
            )
            run.call_until = now() + timedelta(seconds=call_timeout + 5)
            db.commit()
        try:
            if (
                budget.get("streaming_enabled", False)
                and getattr(provider, "streaming_enabled", True)
                and isinstance(provider, StreamingLLMProvider)
            ):
                from .agent_stream import ReplyPublisher

                publisher = ReplyPublisher(app, run_id, token, attempt_no, budget["stream_flush_ms"])
                result = provider.stream_complete(outbound, publisher.content, timeout_seconds=call_timeout)
                publisher.flush(force=True)
            else:
                result = (
                    provider.complete(outbound, timeout_seconds=call_timeout)
                    if callable(getattr(provider, "complete", None))
                    else LLMResult(provider.draft(outbound))
                )
        except Exception as exc:
            with app.state.sessions() as db:
                begin_write(db)
                _, _, run = lock_run(db, run_id)
                run.call_until = None
                end_step(db, model_step_id, error=getattr(exc, "code", "PROVIDER_UNAVAILABLE"))
                record_channel_result(
                    db, policy["provider_id"], runtime, True, getattr(exc, "retry_after_seconds", None)
                )
                db.commit()
            raise
        with app.state.sessions() as db:
            begin_write(db)
            _, _, run = lock_run(db, run_id)
            run.call_until = None
            usage = dict(run.usage_json or {})
            for key, value in result.usage.items():
                if (
                    key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                    and type(value) is int
                    and value >= 0
                ):
                    usage[key] = usage.get(key, 0) + value
            run.usage_json = usage or None
            end_step(
                db,
                model_step_id,
                usage={
                    key: value
                    for key, value in result.usage.items()
                    if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
                    and type(value) is int
                    and value >= 0
                },
            )
            record_channel_result(db, policy["provider_id"], runtime, False)
            db.commit()
        return result.data

    try:
        progress("reading_context")
        from .agent_tools import RunReadTools

        runner = load_symbol(budget["entrypoint"])
        if "tools" in budget:
            answer = runner(
                context,
                invoke,
                progress,
                budget["max_calls"],
                tools=RunReadTools(app, run_id, token, progress),
            )
        else:
            answer = runner(context, invoke, progress, budget["max_calls"])
        from app.modules.agents.context import validate_proposal
        from app.modules.agents.schemas import AgentAnswer

        answer = AgentAnswer.model_validate(
            answer.model_dump() if isinstance(answer, AgentAnswer) else answer
        )
        validate_proposal(answer, context)
        progress("validating")
        with app.state.sessions() as db:
            begin_write(db)
            project, conversation, run = lock_run(db, run_id)
            if run.status != "running" or run.lease_token != token:
                return False
            if aware(run.deadline_at) <= now():
                raise ProviderFailure("AGENT_TIMEOUT")
            valid_inputs(db, project, run, app)
            if set(answer.tool_sources) != {item["id"] for item in run.tool_trace_json}:
                raise ProviderFailure("AGENT_INVALID_OUTPUT")
            if answer.memory_suggestion and not context["facts"].get("memory", {}).get("enabled"):
                raise ProviderFailure("MEMORY_DISABLED")
            # 图片能力在等待期间变更时不发布一份已不适用的提案。
            from app.modules.agents.context import catalog_context

            if (
                run.primary_role == "creative"
                and catalog_context(app, project.kind) != context["facts"]["catalog"]
            ):
                raise ProviderFailure("PROVIDER_CONFIG_CHANGED")
            from app.modules.knowledge.service import citation_evidence

            citations = citation_evidence(db, run.tool_trace_json, answer.citations)
            validation = start_step(
                db,
                run,
                "validation",
                "final_contract",
                {
                    "citation_chunk_ids": answer.citations,
                    "tool_source_ids": answer.tool_sources,
                    "privacy_epoch": run.privacy_epoch,
                    "memory_revision": run.memory_revision,
                },
            )
            end_step(db, validation.id)
            text = answer.reply
            if answer.questions:
                text += "\n" + "\n".join(answer.questions)
            db.add(
                Message(
                    conversation_id=conversation.id,
                    run_id=run.id,
                    seq=conversation.next_seq,
                    role="assistant",
                    text=text,
                    privacy_epoch=run.privacy_epoch,
                    proposal_json=answer.proposal.model_dump(exclude_none=True) if answer.proposal else None,
                    memory_suggestion_json=answer.memory_suggestion,
                    brief_suggestion_json=answer.brief_suggestion,
                    observations_json=run.tool_trace_json,
                    citations_json=citations,
                )
            )
            conversation.next_seq += 1
            run.status, run.stage, run.outcome, run.finished_at = (
                "succeeded",
                "completed",
                answer.outcome,
                now(),
            )
            run.stream_json = None
            db.commit()
        return True
    except (ProviderFailure, DomainError) as exc:
        finish_failed(app, run_id, token, exc.code)
    except Exception:
        finish_failed(app, run_id, token, "AGENT_UNAVAILABLE")
    return False


def maintain_runs(app):
    """Worker 崩溃超时终止，不自动多花一次调用；撤销后清除敏感历史内容。"""
    with app.state.sessions() as db:
        ids = list(
            db.scalars(
                select(AgentRun.id).where(
                    AgentRun.status.in_(["queued", "running"]), AgentRun.deadline_at <= now()
                )
            )
        )
        stale = list(
            db.scalars(
                select(AgentRun.id)
                .join(Project, Project.id == AgentRun.project_id)
                .where(
                    AgentRun.privacy_epoch != Project.privacy_epoch,
                    AgentRun.manifest_json["scrubbed"].as_boolean().is_not(True),
                )
            )
        )
    for run_id in set(ids + stale):
        with app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, run_id)
            if run.status in {"queued", "running"} and (
                aware(run.deadline_at) <= now() or (project and run.privacy_epoch != project.privacy_epoch)
            ):
                run.status, run.stage, run.error_code, run.finished_at = (
                    "failed",
                    "failed",
                    "AUTHORIZATION_CHANGED"
                    if project and run.privacy_epoch != project.privacy_epoch
                    else "AGENT_TIMEOUT",
                    now(),
                )
                run.stream_json = None
                for step in db.scalars(
                    select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.status == "running")
                ):
                    end_step(db, step.id, error=run.error_code)
            if project and run.privacy_epoch != project.privacy_epoch:
                run.context_json, run.manifest_json = {}, {"scrubbed": True}
                for message in db.scalars(select(Message).where(Message.run_id == run_id)):
                    message.text, message.proposal_json = "[授权变化后已清除]", None
                    message.memory_suggestion_json, message.observations_json = None, None
                    message.brief_suggestion_json = None
                run.tool_trace_json = []
                for step in db.scalars(select(AgentStep).where(AgentStep.run_id == run.id)):
                    step.manifest_json = {"scrubbed": True}
                for message in db.scalars(select(Message).where(Message.run_id == run.id)):
                    message.citations_json = None
                run.stream_json = None
            db.commit()
    from app.modules.conversations.support import scrub_support_messages

    scrub_support_messages(app)
    with app.state.sessions() as db:
        stale_memories = list(
            db.scalars(
                select(ProjectMemory.project_id)
                .join(Project, Project.id == ProjectMemory.project_id)
                .where(
                    ProjectMemory.privacy_epoch != Project.privacy_epoch, ProjectMemory.cleared_at.is_(None)
                )
            )
        )
    for project_id in stale_memories:
        with app.state.sessions() as db:
            begin_write(db)
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            scrub_memory(db, project)
            db.commit()


def pending_runs(app, limit=32):
    """有界扫描即可靠投递；没有把用户文字、照片或密钥放入队列。"""
    if not enabled(app):
        return []
    with app.state.sessions() as db:
        return list(
            db.scalars(
                select(AgentRun.id)
                .where(AgentRun.status == "queued")
                .order_by(AgentRun.created_at)
                .limit(limit)
            )
        )

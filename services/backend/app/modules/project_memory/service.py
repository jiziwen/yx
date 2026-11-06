"""长期记忆的读取、明确确认和隐私清理；模型没有写入入口。"""

from sqlalchemy import select

from app.core.db import now
from app.core.errors import DomainError
from app.modules.operations.models import Audit

from .models import ProjectMemory


def memory_enabled(app):
    """可信配置与模块装配共同控制，可停用并保留历史表。"""
    return app.state.config["agent"]["memory_enabled"] and "project_memory" in {
        m.id for m in app.state.modules
    }


def memory_view(app, db, project):
    """读取没有写入副作用；隐私清理尚未执行时也立即隐藏旧内容。"""
    row = db.get(ProjectMemory, project.id)
    available = memory_enabled(app)
    current = bool(row and row.privacy_epoch == project.privacy_epoch and available)
    definitions = app.state.config["agent"]["brief_fields"] if available else []
    keys = {field["key"] for field in definitions}
    return {
        "project_id": project.id,
        "revision": row.revision if row else 0,
        "privacy_epoch": project.privacy_epoch,
        "requirements": row.requirements_json if current else [],
        "updated_at": row.updated_at if current else None,
        "enabled": available,
        "max_items": app.state.config["agent"]["memory_max_items"],
        "fields": {key: value for key, value in row.fields_json.items() if key in keys} if current else {},
        "field_definitions": definitions,
    }


def validate_fields(app, fields):
    """模型与用户都只能使用已配置的文本字段，空字符串表示用户确认清除。"""
    definitions = {field["key"]: field for field in app.state.config["agent"]["brief_fields"]}
    if any(
        key not in definitions or len(value) > definitions[key]["max_length"] for key, value in fields.items()
    ):
        raise DomainError("BRIEF_FIELDS_INVALID", "需求字段或长度不符合当前配置", 422)
    return {key: value.strip() for key, value in fields.items() if value.strip()}


def confirm_memory(app, db, project, user_id, body):
    """调用方已锁定项目；乐观版本保护多窗口编辑，确认不创建图片或改变冻结提案。"""
    if not memory_enabled(app):
        raise DomainError("MEMORY_DISABLED", "项目记忆当前未开放", 503)
    row = db.scalar(select(ProjectMemory).where(ProjectMemory.project_id == project.id).with_for_update())
    revision = row.revision if row else 0
    if project.privacy_epoch != body.expected_privacy_epoch:
        raise DomainError("AUTHORIZATION_CHANGED", "项目授权已变化，请重新查看项目记忆")
    if revision != body.expected_revision:
        raise DomainError("MEMORY_CHANGED", "项目记忆已被更新，请重新查看后确认")
    if len(body.requirements) > app.state.config["agent"]["memory_max_items"]:
        raise DomainError("MEMORY_LIMIT", "记住的要求超过配置上限，请先整理", 422)
    current_fields = row.fields_json if row and row.privacy_epoch == project.privacy_epoch else {}
    fields = validate_fields(app, body.fields) if body.fields is not None else current_fields
    if body.source_run_id:
        from app.modules.agents.models import AgentRun

        run = db.get(AgentRun, body.source_run_id)
        if run is None or run.project_id != project.id or run.privacy_epoch != project.privacy_epoch:
            raise DomainError("NOT_FOUND", "建议不可访问", 404)
        if run.status != "succeeded" or run.memory_revision != revision:
            raise DomainError("MEMORY_CHANGED", "这份建议的记忆版本已变化，请重新整理")
        if (
            body.fields is not None
            and run.budget_json.get("brief_fields") != app.state.config["agent"]["brief_fields"]
        ):
            raise DomainError("MEMORY_CHANGED", "需求卡配置已更新，请重新整理")
    if (
        row
        and row.privacy_epoch == project.privacy_epoch
        and row.requirements_json == body.requirements
        and fields == current_fields
    ):
        return memory_view(app, db, project)
    if row is None:
        row = ProjectMemory(
            project_id=project.id,
            revision=0,
            privacy_epoch=project.privacy_epoch,
            fields_json={},
            confirmed_by_user_id=user_id,
        )
        db.add(row)
    elif (
        row.privacy_epoch != project.privacy_epoch
        or not set(row.requirements_json).issubset(body.requirements)
        or any(fields.get(key) != value for key, value in current_fields.items())
    ):
        row.history_cutoff_at = now()
    row.revision += 1
    row.privacy_epoch, row.requirements_json = project.privacy_epoch, body.requirements
    row.fields_json = fields
    row.confirmed_by_user_id, row.updated_at, row.cleared_at = user_id, now(), None
    db.add(
        Audit(
            actor_id=user_id,
            action="project_memory.confirm" if body.requirements or fields else "project_memory.clear",
            resource_id=project.id,
            summary={"revision": row.revision, "items": len(body.requirements), "fields": len(fields)},
        )
    )
    db.commit()
    return memory_view(app, db, project)


def scrub_memory(db, project):
    """清除旧代次正文不改变有效语义版本，避免让已读取空记忆的新 Run 无故失效。"""
    from app.integrations.call_logging import scrub_calls

    scrub_calls(db, project_id=project.id)
    scrub_m25_private(db, project)
    row = db.get(ProjectMemory, project.id)
    if row and row.privacy_epoch != project.privacy_epoch and row.cleared_at is None:
        row.requirements_json, row.cleared_at = [], now()
        row.fields_json = {}


def scrub_m25_private(db, project):
    """旧草稿和反馈文字同样清除，防止新增模块遗漏隐私清理。"""
    from app.modules.operations.models import QualityFeedback
    from app.modules.projects.models import StudioDraft

    draft = db.get(StudioDraft, project.id)
    if draft and (
        draft.privacy_epoch != project.privacy_epoch or project.lifecycle in {"deleting", "deleted"}
    ):
        draft.draft_json = {}
    for row in db.scalars(select(QualityFeedback).where(QualityFeedback.project_id == project.id)):
        if row.privacy_epoch != project.privacy_epoch or project.lifecycle in {"deleting", "deleted"}:
            row.reason, row.review_note = "[授权变化后已清除]", ""
            row.reference_asset_id, row.grant_active, row.status = None, False, "withdrawn"

"""不可变方案和原子确认用例；模型及前端不能自行改价或创建 Job。"""

import json
from datetime import timedelta, timezone
from hashlib import sha256

from sqlalchemy import select, update

from app.core.db import now, uid
from app.core.errors import DomainError
from app.modules.assets.service import verify_inputs
from app.modules.commerce.models import Account, EntitlementEvent
from app.modules.media_jobs.governance import check_queue
from app.modules.media_jobs.models import Job, Outbox
from app.modules.projects.service import require_project

from .creation import compile_creation, verify_templates
from .models import Approval, Idempotency, Plan


def fingerprint(value: dict) -> str:
    """规范化请求，区分同键的不同语义。"""
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def lookup_request(db, user_id: str, scope: str, key: str, value: dict):
    """同键同内容返回已提交结果，不同内容拒绝。"""
    record = db.scalar(
        select(Idempotency).where(
            Idempotency.user_id == user_id, Idempotency.scope == scope, Idempotency.key == key
        )
    )
    if record and record.fingerprint != fingerprint(value):
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一个请求键不能用于不同操作")
    return record.response_json if record else None


def remember(db, user_id: str, scope: str, key: str, value: dict, response: dict):
    """与业务变更同事务落库，不能提前提交防重记录。"""
    db.add(
        Idempotency(
            user_id=user_id, scope=scope, key=key, fingerprint=fingerprint(value), response_json=response
        )
    )


def plan_view(db, plan: Plan) -> dict:
    """组合不可变方案与独立确认状态。"""
    approval = db.scalar(select(Approval).where(Approval.plan_version_id == plan.id))
    return {
        "id": plan.id,
        "version_no": plan.version_no,
        "brief_revision": plan.brief_revision,
        "spec_json": plan.spec_json,
        "quota_snapshot": plan.quota_snapshot,
        "approval_id": approval.id,
        "approval_status": approval.status,
        "expires_at": approval.expires_at,
    }


def create_plan(db, project_id: str, user_id: str, body, key: str, catalog: dict, gateway):
    """校验完整人物集后冻结素材、版本、供应商和服务器权益快照。"""
    project = require_project(db, project_id, user_id, writable=True)
    scope = f"plan:{project_id}"
    value = body.model_dump(
        exclude={"subject_only"} if "subject_only" not in body.model_fields_set else set()
    )
    legacy_fields = {
        "style_id",
        "style_version",
        "aspect_ratio",
        "count",
        "mood",
        "notes",
        "expected_revision",
    }
    if not (body.model_fields_set - legacy_fields):
        # 部署前已经提交的旧请求键保留原语义哈希，新字段不能改变旧请求的重试结果。
        value = {field: value[field] for field in legacy_fields}
    existing = lookup_request(db, user_id, scope, key, value)
    if existing:
        return db.get(Plan, existing["plan_id"])
    if project.brief_revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "参考图或需求已改变，请刷新项目")
    if body.studio_draft_revision is not None:
        from app.modules.projects.models import StudioDraft

        current = db.get(StudioDraft, project.id)
        if (
            not current
            or current.revision != body.studio_draft_revision
            or current.privacy_epoch != project.privacy_epoch
        ):
            raise DomainError("DRAFT_CONFLICT", "当前创作已变化，请重新准备确认卡")
    style = next(
        (
            s
            for s in catalog["styles"]
            if s["id"] == body.style_id and s["version"] == body.style_version and s["enabled"]
        ),
        None,
    )
    if style is None or style["kind"] != project.kind or body.count > catalog["max_count"]:
        raise DomainError("INVALID_SPEC", "风格或数量不在当前可用目录中", 422)
    creation, manifest, policy = compile_creation(db, project, body, catalog, style, gateway)
    spec = {
        "schema_version": 2,
        **body.model_dump(exclude={"expected_revision"}),
        **creation,
        "kind": "photo_set",
        "style_name": style["name"],
    }
    from .prompts import freeze_prompts

    freeze_prompts(spec, gateway.prompt_config)
    plan = Plan(
        project_id=project.id,
        version_no=project.next_plan_version,
        brief_revision=project.brief_revision,
        privacy_epoch=project.privacy_epoch,
        spec_json=spec,
        input_manifest=manifest,
        quota_snapshot={"photo": body.count},
        execution_policy=policy,
        content_hash=fingerprint({"spec": spec, "inputs": manifest, "policy": policy}),
    )
    project.next_plan_version += 1
    db.add(plan)
    db.flush()
    db.add(Approval(project_id=project.id, plan_version_id=plan.id, expires_at=now() + timedelta(minutes=30)))
    remember(db, user_id, scope, key, value, {"plan_id": plan.id})
    db.commit()
    return plan


def accept_plan(db, approval_id: str, user_id: str, key: str, gateway, catalog) -> dict:
    """锁项目→确认卡→权益；接受、预占、Jobs、防重与 outbox 只有一个提交点。"""
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise DomainError("NOT_FOUND", "确认卡不可访问", 404)
    project = require_project(db, approval.project_id, user_id, writable=True)
    scope, value = "approval.accept", {"approval_id": approval.id}
    existing = lookup_request(db, user_id, scope, key, value)
    if existing:
        return existing
    approval = db.scalar(
        select(Approval)
        .where(Approval.id == approval_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval.status == "accepted":
        raise DomainError("ALREADY_ACCEPTED", "该确认卡已执行，请查看已有任务")
    plan = db.get(Plan, approval.plan_version_id)
    if plan.spec_json.get("studio_draft_revision") is not None:
        from app.modules.projects.models import StudioDraft

        current = db.get(StudioDraft, project.id)
        if (
            not current
            or current.revision != plan.spec_json["studio_draft_revision"]
            or current.privacy_epoch != project.privacy_epoch
        ):
            raise DomainError("PLAN_STALE", "另一侧或窗口已修改创作，请检查最新确认卡")
    compensation = bool(plan.spec_json.get("compensation_feedback_id"))
    if not compensation:
        from .prompts import prompt_policy_hash

        if plan.spec_json.get("prompt_policy_hash") != prompt_policy_hash(gateway.prompt_config):
            raise DomainError("PLAN_STALE", "创作规则已更新，请重新准备确认卡")
    if compensation:
        from app.modules.operations.feedback import current as feedback_current
        from app.modules.operations.models import QualityFeedback

        feedback = db.get(QualityFeedback, plan.spec_json["compensation_feedback_id"])
        if not feedback or feedback.compensation_plan_id != plan.id or feedback.status != "approved":
            raise DomainError("COMPENSATION_UNAVAILABLE", "补偿未获有效审核")
        feedback_current(db, feedback)
    if plan.brief_revision != project.brief_revision or (
        not compensation and plan.version_no != project.next_plan_version - 1
    ):
        raise DomainError("PLAN_STALE", "方案已更新，请使用最新确认卡")
    expiry = (
        approval.expires_at.replace(tzinfo=timezone.utc)
        if approval.expires_at.tzinfo is None
        else approval.expires_at
    )
    if expiry <= now():
        raise DomainError("APPROVAL_EXPIRED", "确认卡已过期，请重新保存方案")
    verify_inputs(db, project, plan.input_manifest, plan.privacy_epoch)
    verify_templates(catalog, plan)
    current_policy = (
        gateway.snapshot("image", plan.execution_policy["provider_id"])
        if compensation
        else gateway.image_policy(plan.spec_json.get("operation", "reference"))
    )
    if current_policy != plan.execution_policy:
        raise DomainError("PROVIDER_CONFIG_CHANGED", "供应商配置已更新，请重新保存方案")
    count = plan.spec_json["count"]
    charge = plan.quota_snapshot["photo"]
    check_queue(db, user_id, count, gateway.queue_limits)
    if not compensation:
        # 条件更新避免并发确认不同卡时把可用权益扣为负数。
        changed = db.execute(
            update(Account)
            .where(Account.project_id == project.id, Account.kind == "photo", Account.available >= count)
            .values(available=Account.available - count, reserved=Account.reserved + count)
        )
        if changed.rowcount != 1:
            raise DomainError("INSUFFICIENT_ENTITLEMENTS", "当前可用权益不足")
        account = db.scalar(select(Account).where(Account.project_id == project.id, Account.kind == "photo"))
    approval.status, approval.acceptance_key = "accepted", key
    jobs = []
    for index in range(1, count + 1):
        job = Job(
            id=uid(),
            project_id=project.id,
            approval_id=approval.id,
            item_index=index,
            provider_id=plan.execution_policy["provider_id"],
        )
        db.add(job)
        db.flush()
        db.add(Outbox(job_id=job.id))
        jobs.append(job.id)
    if charge:
        db.add(
            EntitlementEvent(
                account_id=account.id,
                event_key=f"approval:{approval.id}",
                kind="reserve",
                amount=count,
                reason="确认固定创作方案",
            )
        )
    response = {"approval_id": approval.id, "job_ids": jobs}
    remember(db, user_id, scope, key, value, response)
    db.commit()
    return response

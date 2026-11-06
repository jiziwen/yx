"""独立媒体执行器；外部接单凭据持久化后查询，未知提交禁止重发。"""

import re
from datetime import timedelta
from hashlib import sha256

from sqlalchemy import func, or_, select

from app.core.db import now, uid
from app.core.errors import DomainError
from app.integrations.contracts import AsyncImageProvider, ImageLookup, ImageRequest, ProviderFailure
from app.modules.assets.models import Asset, AssetInput
from app.modules.assets.service import normalize_image, verify_inputs
from app.modules.catalog.live import current_catalog
from app.modules.executions.creation import verify_templates
from app.modules.executions.models import Approval, Plan
from app.modules.media_jobs.governance import acquire_submission, aware, record_channel_result
from app.modules.media_jobs.models import Job, Outbox, ProviderAttempt
from app.modules.media_jobs.service import TERMINAL, settle
from app.modules.projects.models import Project, Subject


def begin_write(db):
    """SQLite 开发模式串行写；PostgreSQL 使用各用例显式行锁。"""
    if db.bind.dialect.name == "sqlite":
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def runtime_options(app, provider_id):
    """部署限额不接受浏览器覆盖；在途账号范围随实际尝试固定。"""
    return app.state.gateway.definitions[provider_id].get("runtime", {})


def error_code(exc):
    """适配器错误只接受有界分类，不把异常正文或 URL 写入事实表。"""
    code = exc.code if isinstance(exc, ProviderFailure) else "PROVIDER_RESULT_UNKNOWN"
    return code if re.fullmatch(r"[A-Z0-9_]{1,50}", code) else "PROVIDER_RESULT_UNKNOWN"


def attempt_for(db, job_id):
    """一项交付只允许一次付费提交，查询复用该尝试。"""
    return db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job_id))


def record_error(app, job_id, exc, *, lookup=False):
    """提交未知不结算；查询失败也不能证明远端失败。"""
    with app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job.status in TERMINAL:
            return
        attempt = attempt_for(db, job_id)
        code = error_code(exc)
        unknown = lookup or not isinstance(exc, ProviderFailure) or exc.unknown
        attempt.error_code = code
        attempt.lookup_lease_until = None
        attempt.status = "unknown" if unknown else "failed"
        runtime = runtime_options(app, job.provider_id)
        attempt.next_poll_at = (
            now() + timedelta(seconds=runtime.get("poll_seconds", 5)) if attempt.upstream_task_id else None
        )
        if unknown:
            job.status, job.error_code, job.lease_until = "reconciliation_required", code, None
            job.revision += 1
        else:
            attempt.finished_at = now()
            settle(db, job, "failed", code)
        record_channel_result(
            db,
            job.provider_id,
            runtime,
            failed=True,
            retry_after_seconds=getattr(exc, "retry_after_seconds", None),
        )
        db.commit()


def complete_output(app, job_id, result):
    """同步返回和核对恢复共用发布事务；迟到结果复核隐私、只结算一次。"""
    content, width, height = normalize_image(result.content)
    storage = app.state.gateway.get("storage")
    with app.state.sessions() as db:
        job = db.get(Job, job_id)
        if job.status in TERMINAL:
            return
        key = f"{job.project_id}/{uid()}.png"
    storage.put(key, content)
    published = False
    try:
        with app.state.sessions() as db:
            begin_write(db)
            job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if job.status in TERMINAL:
                return
            project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
            plan = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
            attempt = attempt_for(db, job_id)
            attempt.status, attempt.error_code, attempt.finished_at = "succeeded", None, now()
            attempt.lookup_lease_until, attempt.next_poll_at = None, None
            attempt.latency_ms = max(0, int((now() - aware(attempt.created_at)).total_seconds() * 1000))
            attempt.usage_json = {
                k: v
                for k, v in result.usage.items()
                if k in {"input_tokens", "output_tokens", "total_tokens", "image_count"}
                and type(v) is int
                and 0 <= v <= 10**12
            }
            if (
                type(result.actual_cost_micros) is int
                and 0 <= result.actual_cost_micros <= 10**15
                and result.currency
                and re.fullmatch(r"[A-Z]{3}", result.currency)
            ):
                attempt.actual_cost_micros, attempt.currency = result.actual_cost_micros, result.currency
            record_channel_result(db, job.provider_id, runtime_options(app, job.provider_id), failed=False)
            try:
                verify_inputs(db, project, plan.input_manifest, plan.privacy_epoch)
            except DomainError:
                settle(db, job, "cancelled", "AUTHORIZATION_CHANGED")
                db.commit()
                return
            asset = Asset(
                id=uid(),
                project_id=job.project_id,
                source_job_id=job.id,
                kind="photo",
                storage_key=key,
                mime_type="image/png",
                byte_size=len(content),
                width=width,
                height=height,
                checksum=sha256(content).hexdigest(),
                development_sample=result.development_sample,
            )
            db.add(asset)
            db.flush()
            inputs = (
                plan.spec_json["items"][job.item_index - 1]["inputs"]
                if plan.spec_json.get("items")
                else plan.input_manifest
            )
            for item in inputs:
                if item.get("asset_id"):
                    db.add(AssetInput(asset_id=asset.id, input_asset_id=item["asset_id"]))
            settle(db, job, "succeeded")
            db.commit()
            published = True
    finally:
        if not published:
            storage.delete(key)


def process_job(app, job_id: str) -> bool:
    """领取与账号许可同事务；提交意图先持久化，再进行唯一一次外部提交。"""
    from evals.m25_runtime import check as check_experiment

    check_experiment(app.state.settings, paid=True)
    with app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "queued":
            return False
        project = db.scalar(select(Project).where(Project.id == job.project_id).with_for_update())
        plan = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
        catalog = current_catalog(app, db)
        try:
            verify_inputs(db, project, plan.input_manifest, plan.privacy_epoch)
            verify_templates(catalog, plan)
            if app.state.gateway.snapshot("image", job.provider_id) != plan.execution_policy:
                raise DomainError("PROVIDER_CONFIG_CHANGED", "供应商配置已变化")
        except (DomainError, ValueError) as exc:
            settle(db, job, "failed", exc.code if isinstance(exc, DomainError) else "PROVIDER_CONFIG_CHANGED")
            db.commit()
            return True
        storage = app.state.gateway.get("storage")
        spec = plan.spec_json
        inputs = spec["items"][job.item_index - 1]["inputs"] if spec.get("items") else plan.input_manifest
        try:
            references = tuple(
                catalog["_images"][(item["style_id"], item["shot_id"])]
                if item.get("source") == "catalog"
                else storage.get(db.get(Asset, item["asset_id"]).storage_key)
                for item in inputs
            )
        except (FileNotFoundError, KeyError, DomainError) as exc:
            settle(db, job, "failed", exc.code if isinstance(exc, DomainError) else "INPUT_UNAVAILABLE")
            db.commit()
            return True
        from app.modules.executions.prompts import legacy_prompt

        item = spec["items"][job.item_index - 1] if spec.get("items") else {}
        prompt = item.get("prompt") or legacy_prompt(spec, inputs)
        request = ImageRequest(
            prompt=prompt,
            aspect_ratio=item.get("aspect_ratio", spec["aspect_ratio"]),
            references=references,
            request_key=job.id,
            operation=spec.get("operation", "reference"),
            input_roles=tuple(item.get("role", "person") for item in inputs),
            subject_bindings=tuple(spec.get("subject_bindings", [])),
            size=item.get("size"),
        )
        provider = app.state.gateway.get(
            "image",
            job.provider_id,
            audit_context={
                "project_id": job.project_id,
                "job_id": job.id,
                "owner_user_id": project.owner_user_id,
                "privacy_epoch": plan.privacy_epoch,
            },
        )
        runtime = runtime_options(app, job.provider_id)
        if not acquire_submission(db, job.provider_id, runtime):
            return False
        job.status, job.lease_until = "running", now() + timedelta(seconds=180)
        job.revision += 1
        db.add(
            ProviderAttempt(
                job_id=job.id,
                provider_id=job.provider_id,
                request_key=job.id,
                account_scope=runtime.get("account_scope") or job.provider_id,
                status="submitting",
                estimated_cost_micros=runtime.get("estimated_cost_micros"),
                estimated_currency=runtime.get("currency"),
            )
        )
        db.commit()
    try:
        if isinstance(provider, AsyncImageProvider):
            submission = provider.submit(request)
            if not isinstance(submission.task_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,200}", submission.task_id
            ):
                raise ProviderFailure("PROVIDER_INVALID_RECEIPT", unknown=True)
            with app.state.sessions() as db:
                begin_write(db)
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                attempt = attempt_for(db, job_id)
                attempt.upstream_task_id, attempt.status = submission.task_id, "pending"
                attempt.next_poll_at = now() + timedelta(seconds=runtime.get("poll_seconds", 5))
                db.commit()
        else:
            complete_output(app, job_id, provider.generate(request))
    except Exception as exc:
        record_error(app, job_id, exc)
    return True


def reconcile_job(app, job_id: str, *, force=False) -> bool:
    """获取查询租约后只读取原任务；无凭据或供应商变更时保持待核对。"""
    with app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status not in {"running", "cancel_requested", "reconciliation_required"}:
            return False
        attempt = attempt_for(db, job_id)
        if not attempt or not attempt.upstream_task_id:
            return False
        if attempt.lookup_lease_until and aware(attempt.lookup_lease_until) > now():
            return False
        if not force and attempt.next_poll_at and aware(attempt.next_poll_at) > now():
            return False
        plan = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
        try:
            provider = app.state.gateway.get(
                "image",
                job.provider_id,
                audit_context={
                    "project_id": job.project_id,
                    "job_id": job.id,
                    "owner_user_id": db.get(Project, job.project_id).owner_user_id,
                    "privacy_epoch": plan.privacy_epoch,
                },
            )
            if app.state.gateway.snapshot(
                "image", job.provider_id
            ) != plan.execution_policy or not isinstance(provider, AsyncImageProvider):
                raise ValueError("frozen provider unavailable")
        except ValueError:
            attempt.next_poll_at = now() + timedelta(minutes=1)
            attempt.error_code = "PROVIDER_CONFIG_CHANGED"
            job.status, job.error_code = "reconciliation_required", "PROVIDER_CONFIG_CHANGED"
            job.revision += 1
            db.commit()
            return False
        attempt.lookup_lease_until = now() + timedelta(seconds=180)
        task_id, request_key = attempt.upstream_task_id, attempt.request_key
        db.commit()
    try:
        lookup = provider.lookup(task_id, request_key)
        if not isinstance(lookup, ImageLookup) or lookup.status not in {
            "succeeded",
            "failed",
            "cancelled",
            "pending",
            "unknown",
        }:
            raise ProviderFailure("PROVIDER_STATUS_UNKNOWN", unknown=True)
        if lookup.status == "succeeded":
            if lookup.result is None:
                raise ProviderFailure("PROVIDER_INVALID_OUTPUT", unknown=True)
            complete_output(app, job_id, lookup.result)
        else:
            with app.state.sessions() as db:
                begin_write(db)
                job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if job.status in TERMINAL:
                    return True
                attempt = attempt_for(db, job_id)
                attempt.lookup_lease_until = None
                attempt.status = "unknown" if lookup.status == "unknown" else lookup.status
                attempt.error_code = (
                    lookup.error_code
                    if lookup.error_code and re.fullmatch(r"[A-Z0-9_]{1,50}", lookup.error_code)
                    else None
                )
                runtime = runtime_options(app, job.provider_id)
                attempt.next_poll_at = now() + timedelta(seconds=runtime.get("poll_seconds", 5))
                if lookup.status in {"failed", "cancelled"}:
                    attempt.finished_at = now()
                    attempt.next_poll_at = None
                    record_channel_result(db, job.provider_id, runtime, failed=lookup.status == "failed")
                    settle(db, job, lookup.status, attempt.error_code)
                elif lookup.status == "unknown":
                    job.status, job.error_code = (
                        "reconciliation_required",
                        attempt.error_code or "PROVIDER_STATUS_UNKNOWN",
                    )
                    job.revision += 1
                else:
                    if job.status == "reconciliation_required":
                        job.status, job.error_code = "running", None
                        job.revision += 1
                    job.lease_until = now() + timedelta(seconds=180)
                db.commit()
    except Exception as exc:
        record_error(app, job_id, exc, lookup=True)
    return True


def maintenance(app) -> None:
    """恢复崩溃任务并分批删除撤销人物的参考与派生文件；每轮有界可重试。"""
    from app.modules.operations.models import QualityFeedback
    from app.modules.project_memory.service import scrub_m25_private
    from app.modules.projects.models import StudioDraft

    # 普通本地维护进程只清理隔离实验根；实验进程由外层监督器在退出后清理自身。
    if app.state.settings.app_env == "development" and not app.state.settings.m25_run_id:
        import time

        from evals.m25 import cleanup

        if time.monotonic() >= getattr(app.state, "next_experiment_cleanup", 0):
            cleanup()
            app.state.next_experiment_cleanup = time.monotonic() + 60
    with app.state.sessions() as db:
        begin_write(db)
        ids = set(
            db.scalars(
                select(StudioDraft.project_id)
                .join(Project)
                .where(StudioDraft.privacy_epoch != Project.privacy_epoch)
            )
        )
        ids |= set(
            db.scalars(
                select(QualityFeedback.project_id)
                .join(Project)
                .where(QualityFeedback.privacy_epoch != Project.privacy_epoch)
            )
        )
        for project_id in sorted(ids):
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            scrub_m25_private(db, project)
        expired = list(
            db.scalars(
                select(Job)
                .where(Job.status.in_(["running", "cancel_requested"]), Job.lease_until < now())
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for job in expired:
            job.status, job.error_code = "reconciliation_required", "WORKER_INTERRUPTED"
            job.revision += 1
            attempt = attempt_for(db, job.id)
            if attempt and attempt.status in {"pending", "submitting"}:
                attempt.status, attempt.error_code = "unknown", "WORKER_INTERRUPTED"
        revoked = select(Subject.id).where(Subject.authorization_state == "revoked")
        parents = list(
            db.scalars(
                select(Asset)
                .where(
                    (Asset.subject_id.in_(revoked) & (Asset.status != "deleted"))
                    | (Asset.status == "deleting")
                )
                .limit(50)
            )
        )
        for parent in parents:
            parent.status = "deleting"
            for child in db.scalars(
                select(Asset)
                .join(AssetInput, AssetInput.asset_id == Asset.id)
                .where(AssetInput.input_asset_id == parent.id, Asset.status != "deleted")
            ):
                child.status = "deleting"
        db.commit()
    with app.state.sessions() as db:
        begin_write(db)
        for asset in db.scalars(select(Asset).where(Asset.status == "deleting").limit(50)):
            # 标记每一代的孩子后才物理删除，避免连续编辑的孙代被留在 ready 状态。
            for child in db.scalars(
                select(Asset)
                .join(AssetInput, AssetInput.asset_id == Asset.id)
                .where(AssetInput.input_asset_id == asset.id, Asset.status == "ready")
            ):
                child.status = "deleting"
            app.state.gateway.get("storage").delete(asset.storage_key)
            asset.status = "deleted"
        db.commit()


def queued_ids(db, limit=64):
    """按用户轮转共享同一调度顺序，已投递但未领取的事件也可重新投递。"""
    ranked = (
        select(
            Job.id.label("job_id"),
            Job.created_at,
            func.row_number()
            .over(partition_by=Project.owner_user_id, order_by=(Job.created_at, Job.id))
            .label("user_rank"),
        )
        .join(Project, Project.id == Job.project_id)
        .join(Outbox, Outbox.job_id == Job.id)
        .where(Outbox.status.in_(["pending", "published"]), Job.status == "queued")
        .subquery()
    )
    return list(
        db.scalars(
            select(ranked.c.job_id)
            .order_by(ranked.c.user_rank, ranked.c.created_at, ranked.c.job_id)
            .limit(limit)
        )
    )


def tick(app) -> int:
    """先恢复已有任务，再按用户轮转选择有界队列；重复调度不会重复提交。"""
    maintenance(app)
    with app.state.sessions() as db:
        recoveries = list(
            db.scalars(
                select(ProviderAttempt.job_id)
                .join(Job, Job.id == ProviderAttempt.job_id)
                .where(
                    Job.status.in_(["running", "cancel_requested", "reconciliation_required"]),
                    ProviderAttempt.upstream_task_id.is_not(None),
                    ProviderAttempt.next_poll_at <= now(),
                    or_(
                        ProviderAttempt.lookup_lease_until.is_(None),
                        ProviderAttempt.lookup_lease_until <= now(),
                    ),
                )
                .order_by(ProviderAttempt.next_poll_at)
                .limit(8)
            )
        )
    for job_id in recoveries:
        reconcile_job(app, job_id)
    with app.state.sessions() as db:
        ids = queued_ids(db)
    processed = 0
    for job_id in ids:
        processed += bool(process_job(app, job_id))
        if processed >= 8:
            break
    return processed

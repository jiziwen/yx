"""知识队列独立执行，外部 embedding 无长数据库事务；重投不重复调用。"""

from datetime import timedelta

from sqlalchemy import select

from app.core.db import now, uid
from app.modules.media_jobs.governance import aware
from app.workers.runtime import begin_write

from .models import KnowledgeChunk, KnowledgeIndexJob, KnowledgeVersion
from .service import decode_source, embedder, spec, tokens


def pending(app):
    """有界扫描即可靠投递，队列只携带索引任务ID。"""
    if "knowledge" not in {m.id for m in app.state.modules}:
        return []
    with app.state.sessions() as db:
        return list(
            db.scalars(
                select(KnowledgeIndexJob.id)
                .where(KnowledgeIndexJob.status == "queued")
                .order_by(KnowledgeIndexJob.created_at)
                .limit(16)
            )
        )


def process(app, job_id):
    """领取令牌唯一；崩溃后的running保留为失败，用户重新导入才新建付费调用。"""
    with app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(select(KnowledgeIndexJob).where(KnowledgeIndexJob.id == job_id).with_for_update())
        if not job or job.status != "queued":
            return False
        version = db.get(KnowledgeVersion, job.version_id)
        token = uid()
        job.lease_token = token
        job.status = "running"
        version.status = "indexing"
        job.deadline_at = now() + timedelta(seconds=app.state.config["knowledge"]["index_timeout_seconds"])
        source_key, format, frozen = version.source_key, version.source_format, version.embedding_spec
        db.commit()
    try:
        if spec(app) != frozen:
            raise ValueError("EMBEDDING_SPEC_CHANGED")
        text = decode_source(
            app.state.gateway.get("storage").get(source_key),
            format,
            app.state.config["knowledge"]["max_text_chars"],
        )
        size = app.state.config["knowledge"]["chunk_chars"]
        chunks = [text[start : start + size] for start in range(0, len(text), size - 80)]
        if len(chunks) > 100:
            raise ValueError("KNOWLEDGE_SOURCE_TOO_LARGE")
        from evals.m25_runtime import check as check_experiment

        check_experiment(app.state.settings, paid=True)
        vectors, usage = embedder(app).embed(
            chunks, timeout_seconds=app.state.config["knowledge"]["index_timeout_seconds"]
        )
        with app.state.sessions() as db:
            begin_write(db)
            job = db.scalar(select(KnowledgeIndexJob).where(KnowledgeIndexJob.id == job_id).with_for_update())
            version = db.get(KnowledgeVersion, job.version_id)
            if (
                job.status != "running"
                or job.lease_token != token
                or aware(job.deadline_at) <= now()
                or spec(app) != frozen
            ):
                raise ValueError("KNOWLEDGE_INDEX_INTERRUPTED")
            for index, (part, vector) in enumerate(zip(chunks, vectors)):
                db.add(
                    KnowledgeChunk(
                        version_id=version.id,
                        ordinal=index + 1,
                        text=part,
                        locator=f"片段 {index + 1}",
                        search_text=" ".join(tokens(part)),
                        embedding=vector,
                    )
                )
            version.status = "ready"
            job.status = "succeeded"
            job.usage_json = usage or None
            job.finished_at = now()
            db.commit()
        return True
    except Exception as exc:
        code = getattr(exc, "code", None) or (
            str(exc)
            if str(exc)
            in {"EMBEDDING_SPEC_CHANGED", "KNOWLEDGE_INDEX_INTERRUPTED", "KNOWLEDGE_SOURCE_TOO_LARGE"}
            else "KNOWLEDGE_INDEX_FAILED"
        )
        with app.state.sessions() as db:
            begin_write(db)
            job = db.scalar(select(KnowledgeIndexJob).where(KnowledgeIndexJob.id == job_id).with_for_update())
            if job and job.status == "running" and job.lease_token == token:
                version = db.get(KnowledgeVersion, job.version_id)
                version.status = "failed"
                version.error_code = code
                job.status = "failed"
                job.error_code = code
                job.finished_at = now()
                db.commit()
        return False


def maintain(app):
    """过期索引只终止，不自动重复提交 embedding。旧发布版本保持可用。"""
    with app.state.sessions() as db:
        begin_write(db)
        for job in db.scalars(
            select(KnowledgeIndexJob)
            .where(KnowledgeIndexJob.status == "running", KnowledgeIndexJob.deadline_at <= now())
            .with_for_update(skip_locked=True)
        ):
            version = db.get(KnowledgeVersion, job.version_id)
            version.status = "failed"
            version.error_code = "KNOWLEDGE_INDEX_INTERRUPTED"
            job.status = "failed"
            job.error_code = "KNOWLEDGE_INDEX_INTERRUPTED"
            job.finished_at = now()
        db.commit()

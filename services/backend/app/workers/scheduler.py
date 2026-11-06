"""可靠投递扫描器；持锁投递失败回滚，重复消息由 Job 状态机过滤。"""

import logging
import time

from sqlalchemy import or_, select

from app.core.db import now
from app.main import create_app
from app.modules.media_jobs.models import Job, Outbox, ProviderAttempt

from .agent_runtime import pending_runs
from .celery_app import agent, knowledge, maintain, media, reconcile
from .runtime import begin_write, queued_ids


def dispatch(app):
    """周期重新投递未完成消息，避免 Redis 丢失造成任务永久搁置。"""
    with app.state.sessions() as db:
        begin_write(db)
        ordered = queued_ids(db, limit=100)
        events = list(
            db.scalars(
                select(Outbox)
                .join(Job, Job.id == Outbox.job_id)
                .where(Outbox.status.in_(["pending", "published"]), Job.id.in_(ordered))
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        by_job = {event.job_id: event for event in events}
        for job_id in ordered:
            if job_id not in by_job:
                continue
            event = by_job[job_id]
            media.delay(event.job_id)
            event.status = "published"
        db.commit()
    with app.state.sessions() as db:
        ids = list(
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
                .limit(100)
            )
        )
    for job_id in ids:
        reconcile.delay(job_id)
    maintain.delay()
    for run_id in pending_runs(app):
        agent.delay(run_id)
    from app.modules.knowledge.worker import pending

    for job_id in pending(app):
        knowledge.delay(job_id)


def main():
    """只扫描与投递，实际清理由 maintenance Worker 执行。"""
    app = create_app()
    while True:
        try:
            dispatch(app)
        except Exception as exc:
            logging.error("dispatch_failed kind=%s", type(exc).__name__)
        time.sleep(10)


if __name__ == "__main__":
    main()

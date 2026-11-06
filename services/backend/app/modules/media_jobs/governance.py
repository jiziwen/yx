"""用共享数据库串行化短小的容量决策，外部网络调用始终在事务之外。"""

from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.db import now
from app.core.errors import DomainError
from app.modules.projects.models import Project

from .models import Job, ProviderAttempt, RuntimeGate

ACTIVE = ("queued", "running", "cancel_requested", "reconciliation_required")


def aware(value):
    """SQLite 不保存 timezone，比较前统一为 UTC。"""
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def lock_gate(db, scope: str) -> RuntimeGate:
    """首次使用原子插入，随后行锁；协调失败时事务失败，不发新请求。"""
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    db.execute(insert(RuntimeGate).values(scope=scope).on_conflict_do_nothing(index_elements=["scope"]))
    return db.scalar(
        select(RuntimeGate)
        .where(RuntimeGate.scope == scope)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def check_queue(db, user_id: str, count: int, limits: dict) -> None:
    """全局入口锁下校验总队列、用户待处理和批量，失败不预占权益。"""
    lock_gate(db, "queue")
    if count > limits["max_batch"]:
        raise DomainError("BATCH_LIMIT", "本次张数超过当前批量上限", 422)
    total = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(ACTIVE)))
    own = db.scalar(
        select(func.count())
        .select_from(Job)
        .join(Project, Project.id == Job.project_id)
        .where(Project.owner_user_id == user_id, Job.status.in_(ACTIVE))
    )
    if own + count > limits["max_user_pending"]:
        raise DomainError("USER_PENDING_LIMIT", "待处理任务较多，请等已有创作完成后再确认", 409)
    if total + count > limits["max_pending"]:
        raise DomainError("QUEUE_CAPACITY", "当前创作队列已满，请稍后再确认", 409)


def acquire_submission(db, provider_id: str, runtime: dict) -> bool:
    """持有账号锁时检查在途和速率，提交记录同事务落库后才释放锁。"""
    scope = runtime.get("account_scope") or provider_id
    gate = lock_gate(db, f"provider:{scope}")
    current = now()
    if gate.retry_after_until and aware(gate.retry_after_until) > current:
        return False
    if gate.paused_until and aware(gate.paused_until) > current:
        return False
    in_flight = db.scalar(
        select(func.count())
        .select_from(ProviderAttempt)
        .where(
            ProviderAttempt.account_scope == scope,
            ProviderAttempt.status.in_(["submitting", "pending", "unknown"]),
        )
    )
    from app.modules.agents.models import AgentRun

    in_flight += db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.account_scope == scope,
            AgentRun.call_until > current,
        )
    )
    if in_flight >= runtime.get("max_in_flight", 4):
        return False
    if aware(gate.window_started_at) + timedelta(minutes=1) <= current:
        gate.window_started_at, gate.request_count = current, 0
    if gate.request_count >= runtime.get("requests_per_minute", 30):
        return False
    if gate.paused_until:
        # 冷却后只放行一次探测；其他 Worker 等待该结果或下次冷却。
        gate.paused_until = current + timedelta(seconds=runtime.get("cooldown_seconds", 60))
    gate.request_count += 1
    return True


def record_channel_result(
    db, provider_id: str, runtime: dict, failed: bool, retry_after_seconds: int | None = None
) -> None:
    """通道失败熔断；冷却后下一次有容量的请求为受控探测，不重发旧任务。"""
    gate = lock_gate(db, f"provider:{runtime.get('account_scope') or provider_id}")
    gate.consecutive_failures = gate.consecutive_failures + 1 if failed else 0
    if failed and gate.consecutive_failures >= runtime.get("failure_threshold", 5):
        gate.paused_until = now() + timedelta(seconds=runtime.get("cooldown_seconds", 60))
    if not failed:
        gate.paused_until = None
    if type(retry_after_seconds) is int and retry_after_seconds > 0:
        deadline = now() + timedelta(seconds=min(retry_after_seconds, 86400 * 365))
        gate.retry_after_until = max(aware(gate.retry_after_until) or deadline, deadline)

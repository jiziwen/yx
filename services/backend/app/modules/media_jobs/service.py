"""任务状态机与权益结算；只有终结的已知结果才释放/消耗预占。"""

from sqlalchemy import select

from app.core.errors import DomainError
from app.modules.commerce.models import Account, EntitlementEvent

from .models import Job, Outbox

TERMINAL = {"succeeded", "failed", "cancelled"}


def settle(db, job: Job, status: str, error_code: str | None = None):
    """行锁和事件唯一键保证终态一次结算；未知结果不调用此函数。"""
    if job.status in TERMINAL:
        return
    if status not in TERMINAL:
        raise ValueError("只允许明确终态结算")
    from app.modules.executions.models import Approval, Plan

    plan = db.get(Plan, db.get(Approval, job.approval_id).plan_version_id)
    if not plan.spec_json.get("compensation_feedback_id"):
        account = db.scalar(
            select(Account)
            .where(Account.project_id == job.project_id, Account.kind == "photo")
            .with_for_update()
        )
        # 数据错误不能默默制造权益；整个交付事务回滚待核对。
        if account.reserved < 1:
            raise DomainError("SETTLEMENT_CONFLICT", "任务结算需要核对")
        account.reserved -= 1
        if status == "succeeded":
            account.consumed += 1
        else:
            account.available += 1
        db.add(
            EntitlementEvent(
                account_id=account.id,
                event_key=f"job:{job.id}:settle",
                kind="consume" if status == "succeeded" else "release",
                amount=1,
                reason=status,
            )
        )
    job.status, job.error_code, job.lease_until = status, error_code, None
    job.revision += 1
    outbox = db.scalar(select(Outbox).where(Outbox.job_id == job.id))
    if outbox:
        outbox.status = "done"


def cancel(db, job: Job):
    """排队任务立即取消并返还；外部提交后只标记请求，等待供应商事实。"""
    if job.status == "queued":
        settle(db, job, "cancelled")
    elif job.status == "running":
        job.status = "cancel_requested"
        job.revision += 1
    elif job.status == "reconciliation_required":
        raise DomainError("RECONCILIATION_REQUIRED", "外部结果尚未确定，需要核对后才能结算")

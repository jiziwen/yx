"""media_jobs 模块数据所有权；字段语义与约束由 Alembic 迁移固化。"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record, now


class Job(Record, Base):
    """每张照片一个 Job；未知外部结果保留预占，不自动重发。"""

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("approval_id", "item_index", name="uq_job_delivery"),
        {"comment": "持久化媒体执行与结算状态"},
    )
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True, comment="所属项目")
    approval_id: Mapped[str] = mapped_column(
        ForeignKey("execution_approvals.id"), comment="用户已接受的执行授权"
    )
    item_index: Mapped[int] = mapped_column(comment="组内交付项序号，从 1 开始")
    status: Mapped[str] = mapped_column(
        String(32),
        default="queued",
        index=True,
        comment="queued/running/succeeded/failed/cancelled/cancel_requested/reconciliation_required",
    )
    provider_id: Mapped[str] = mapped_column(String(80), comment="方案冻结供应商 ID")
    error_code: Mapped[str | None] = mapped_column(String(50), comment="可公开的错误分类")
    revision: Mapped[int] = mapped_column(default=1, comment="每次状态变化递增")
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="进程崩溃后转待核对，不盲目重发"
    )


class Outbox(Record, Base):
    """数据库内的可靠投递意图，与任务创建同事务。"""

    __tablename__ = "outbox_events"
    __table_args__ = {"comment": "Job 创建与异步投递之间的持久化桥梁"}
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True, comment="待投递 Job")
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True, comment="pending/published/done"
    )


class ProviderAttempt(Record, Base):
    """外部提交证据；不记录原始照片、密钥和供应商正文。"""

    __tablename__ = "provider_attempts"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_provider_attempt_request"),
        {"comment": "供应商调用尝试和不确定结果"},
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id"), unique=True, comment="本阶段每 Job 最多一次外部提交"
    )
    provider_id: Mapped[str] = mapped_column(String(80), comment="供应商注册 ID")
    status: Mapped[str] = mapped_column(String(24), comment="submitting/succeeded/failed/unknown")
    request_key: Mapped[str] = mapped_column(String(36), comment="稳定请求键；不承诺上游幂等")
    account_scope: Mapped[str] = mapped_column(String(64), index=True, comment="共享供应商账号范围")
    upstream_task_id: Mapped[str | None] = mapped_column(String(200), comment="上游接单凭据，不对用户公开")
    error_code: Mapped[str | None] = mapped_column(String(50), comment="脱敏错误分类")
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="最早查询时间")
    lookup_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="核对查询租约"
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="已知外部终态时间")
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, comment="本地观测的端到端耗时")
    usage_json: Mapped[dict | None] = mapped_column(JSON, comment="数值用量白名单，不含供应商正文")
    estimated_cost_micros: Mapped[int | None] = mapped_column(
        BigInteger, comment="估算微单位金额，未知为 null"
    )
    estimated_currency: Mapped[str | None] = mapped_column(String(3), comment="估算金额币种，与确认费用分开")
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger, comment="确认微单位金额，未知为 null")
    currency: Mapped[str | None] = mapped_column(String(3), comment="费用币种；不能将估算作为实付")


class RuntimeGate(Base):
    """所有 Worker 共用的数据库行锁；未知远端任务不因本地租约过期释放槽位。"""

    __tablename__ = "runtime_gates"
    __table_args__ = {"comment": "共享账号并发、速率与入口容量协调"}
    scope: Mapped[str] = mapped_column(String(80), primary_key=True, comment="入口或账号的稳定范围")
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, comment="分钟窗口起点"
    )
    request_count: Mapped[int] = mapped_column(default=0, comment="窗口内实际提交次数")
    consecutive_failures: Mapped[int] = mapped_column(default=0, comment="连续外部调用失败次数")
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="熔断截止时间")
    retry_after_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="供应商退避截止，不因其他任务成功提前清除"
    )

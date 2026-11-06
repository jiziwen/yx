"""短 Agent Run 的权威状态、冻结上下文、预算和执行权。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class AgentRun(Record, Base):
    """消息即可靠投递意图；调度器重扫 queued，调用后崩溃不自动重发 LLM。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "client_message_id", name="uq_agent_message"),
        {"comment": "受总预算、隐私和取消屏障保护的短 Agent 运行"},
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True, comment="所属会话，禁止跨项目历史拼接"
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), index=True, comment="拥有者和隐私校验的项目范围"
    )
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    primary_role: Mapped[str] = mapped_column(String(20), default="creative")
    release_json: Mapped[dict] = mapped_column(JSON, default=dict)
    client_message_id: Mapped[str] = mapped_column(String(100), comment="客户端消息幂等键")
    request_hash: Mapped[str] = mapped_column(String(64), comment="原始请求的规范 SHA256，冲突时拒绝")
    status: Mapped[str] = mapped_column(
        String(20), default="queued", index=True, comment="queued/running/succeeded/failed/cancelled"
    )
    stage: Mapped[str] = mapped_column(
        String(32), default="queued", comment="真实执行阶段，不代表 token 流或推理过程"
    )
    outcome: Mapped[str | None] = mapped_column(
        String(20), comment="needs_input/plan_ready/answer，成功时赋值"
    )
    error_code: Mapped[str | None] = mapped_column(String(50), comment="稳定脱敏错误码，无上游原文")
    brief_revision: Mapped[int] = mapped_column(comment="入队时冻结的项目需求版本")
    privacy_epoch: Mapped[int] = mapped_column(comment="入队时冻结的隐私代次")
    policy_json: Mapped[dict] = mapped_column(JSON, comment="冻结的 LLM 插件 ID、版本与配置摘要")
    context_json: Mapped[dict] = mapped_column(JSON, comment="当前草稿、完整历史和只读元数据；不含照片")
    manifest_json: Mapped[dict] = mapped_column(JSON, comment="来源 ID、上下文摘要、裁剪与预算估算")
    budget_json: Mapped[dict] = mapped_column(JSON, comment="冻结的编排入口、总预算与上下文策略")
    calls: Mapped[int] = mapped_column(default=0, comment="累计实际模型调用次数，发送前提交")
    memory_revision: Mapped[int] = mapped_column(default=0, comment="本轮读取的用户确认记忆版本")
    tool_calls: Mapped[int] = mapped_column(default=0, comment="累计只读工具尝试，错误也消耗预算")
    tool_trace_json: Mapped[list] = mapped_column(
        JSON, default=list, comment="有界只读查询结果和来源，不含供应商原文"
    )
    usage_json: Mapped[dict | None] = mapped_column(JSON, comment="供应商数值 token 白名单，未知为 null")
    stream_json: Mapped[dict | None] = mapped_column(JSON, comment="当前模型尝试的有界临时回复，终态清除")
    model: Mapped[str] = mapped_column(String(120), comment="本轮冻结模型显示名")
    development_sample: Mapped[bool] = mapped_column(default=False, comment="显式开发模型标记")
    account_scope: Mapped[str] = mapped_column(String(80), index=True, comment="共享模型调用限额范围")
    lease_token: Mapped[str | None] = mapped_column(String(36), comment="唯一提交权令牌，重复投递无法接管")
    call_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="远端调用槽位期限，取消仍保留至回包或超时"
    )
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="入队起算总截止时间，重试不清零"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="本地运行终态 UTC 时间"
    )

    @property
    def draft_context(self):
        """仅供拥有者比较建议来源；撤销清理后不再返回旧草稿。"""
        return self.context_json.get("facts", {}).get("draft")

    @property
    def analysis_sources(self):
        """已授权观察的准确来源，图像字节不随会话返回。"""
        return self.manifest_json.get("vision", {}).get("images", [])

    @property
    def reply_preview(self):
        """临时回复不属于正式消息，只在运行中公开，失败/取消/完成立即隐藏。"""
        return self.stream_json if self.status == "running" else None


class AgentStep(Record, Base):
    """公开调用步骤和上下文来源摘要，不记录隐藏思考或供应商正文。"""

    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    manifest_json: Mapped[dict] = mapped_column(JSON)
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(60))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

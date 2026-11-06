"""会话与消息所有权；隐私代次变化后历史不能继续进入上下文。"""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Record


class Conversation(Record, Base):
    """第一阶段每个项目一个创作会话，轮次由数据库串行分配。"""

    __tablename__ = "conversations"
    __table_args__ = {"comment": "拥有者通过项目绑定的创作会话"}
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), unique=True, comment="唯一所属项目"
    )
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    context_project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    scope_key: Mapped[str | None] = mapped_column(String(150), unique=True)
    entry_mode: Mapped[str] = mapped_column(String(20), default="auto")
    handoff_status: Mapped[str] = mapped_column(String(20), default="bot", index=True)
    assigned_staff_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(default=0)

    @property
    def bound_project_id(self):
        """旧创作会话保留唯一项目列；客服可独立绑定项目或无项目。"""
        return self.context_project_id or self.project_id

    next_seq: Mapped[int] = mapped_column(default=1, comment="下一消息顺序号，项目/会话锁下分配")


class Message(Record, Base):
    """仅保存已提交的用户输入或最终回复，不保存隐藏思考和原始照片。"""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_message_seq"),
        UniqueConstraint("conversation_id", "client_message_id", name="uq_support_message"),
        {"comment": "按顺序提交的用户消息与最终助手回复"},
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), index=True, comment="所属会话"
    )
    run_id: Mapped[str] = mapped_column(String(36), index=True, comment="所属需求处理轮次 ID")
    seq: Mapped[int] = mapped_column(comment="会话内单调顺序，非时间戳排序")
    role: Mapped[str] = mapped_column(String(16), comment="user/assistant，不接受客户端角色")
    text: Mapped[str] = mapped_column(String(2000), comment="私有消息正文，撤销清理可替换")
    privacy_epoch: Mapped[int] = mapped_column(comment="项目隐私代次，不一致即不可见")
    proposal_json: Mapped[dict | None] = mapped_column(JSON, comment="受白名单校验的表单建议，不是正式 Plan")
    memory_suggestion_json: Mapped[list | None] = mapped_column(JSON, comment="待用户明确确认的记忆建议")
    brief_suggestion_json: Mapped[dict | None] = mapped_column(
        JSON, comment="待用户确认的结构化需求补丁，不自动保存"
    )
    observations_json: Mapped[list | None] = mapped_column(JSON, comment="本轮只读查询的脱敏结果与观察时间")

    citations_json: Mapped[list | None] = mapped_column(JSON, comment="后端验证的已发布知识引用")
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), comment="员工消息真实操作者")
    client_message_id: Mapped[str | None] = mapped_column(String(100), comment="人工期间消息幂等键")

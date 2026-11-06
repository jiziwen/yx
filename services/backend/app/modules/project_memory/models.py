"""每项目一份版本化长期记忆；授权代次变化立即屏蔽旧内容。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, now


class ProjectMemory(Base):
    """只保留用户确认的要求，审计记录版本和条数而不复制正文。"""

    __tablename__ = "project_memories"
    __table_args__ = {"comment": "拥有者明确确认的项目长期要求"}
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id"), primary_key=True, comment="唯一所属项目"
    )
    revision: Mapped[int] = mapped_column(default=1, comment="用户确认或清空时单调递增")
    privacy_epoch: Mapped[int] = mapped_column(comment="内容所属隐私代次，不一致立即不可读")
    requirements_json: Mapped[list] = mapped_column(
        JSON, default=list, comment="有界的用户确认要求，不是权限或状态事实"
    )
    fields_json: Mapped[dict] = mapped_column(JSON, default=dict, comment="用户确认的配置化创作需求字段")
    confirmed_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), comment="最近明确确认的拥有者")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, comment="最近用户确认的 UTC 时间"
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="旧隐私代次正文完成清除的时间"
    )
    history_cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="删除要求后不再纳入更早聊天，防止被遗忘内容复活"
    )

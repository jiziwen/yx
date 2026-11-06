"""有界临时回复；旧消息/Run 保留，终态不依赖临时内容恢复。"""

import sqlalchemy as sa
from alembic import op

revision = "a38f94cce1d2"
down_revision = "ffba47dfea56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """单个可空字段，旧运行记录自然回填 null。"""
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(
            sa.Column("stream_json", sa.JSON(), nullable=True, comment="当前模型尝试的有界临时回复，终态清除")
        )


def downgrade() -> None:
    """移除临时回复字段，不删除正式消息和生成记录。"""
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("stream_json")

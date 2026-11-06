"""${message}；只通过 Alembic 执行，回退前先备份业务数据。"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """创建本阶段实际使用的数据表和约束，不代表完整 25 表已落地。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """破坏性回退；仅开发验证或已有备份的维护操作使用。"""
    ${downgrades if downgrades else "pass"}

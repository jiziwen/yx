"""删除照片时显式保留已确认的通用文字偏好；不从历史或模型重建。"""

from pydantic import Field

from app.core.db import now
from app.core.errors import DomainError
from app.core.schemas import Input
from app.modules.operations.models import Audit

from .models import ProjectMemory


class KeepPreferences(Input):
    """用户逐项选择并声明与图片无关，默认不保留任何旧内容。"""

    expected_memory_revision: int = Field(ge=0)
    requirements: list[str] = Field(default_factory=list, max_length=12)
    generic_text_only: bool = False


def selected_preferences(db, project, body):
    """删除前在项目锁内验证已有确认内容与版本，不能提交新的隐藏观察。"""
    if body is None or not body.requirements:
        return []
    row = db.get(ProjectMemory, project.id)
    if (
        not body.generic_text_only
        or not row
        or row.privacy_epoch != project.privacy_epoch
        or row.revision != body.expected_memory_revision
        or not set(body.requirements).issubset(row.requirements_json)
    ):
        raise DomainError("MEMORY_CHANGED", "请重新选择已确认且脱离图片成立的通用文字要求")
    return list(dict.fromkeys(body.requirements))


def retain_preferences(db, project, user_id, selected):
    """只把本次选中原话迁入新代次；结构化图像事实及旧聊天继续清理。"""
    if not selected:
        return
    row = db.get(ProjectMemory, project.id)
    row.requirements_json, row.fields_json = selected, {}
    row.privacy_epoch = project.privacy_epoch
    row.revision += 1
    row.history_cutoff_at = row.updated_at = now()
    row.confirmed_by_user_id = user_id
    db.add(
        Audit(
            actor_id=user_id,
            action="project_memory.retain_generic",
            resource_id=project.id,
            summary={"revision": row.revision, "items": len(selected)},
        )
    )

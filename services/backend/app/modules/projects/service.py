"""项目访问与修改守卫；外部越权对象统一返回 404。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError

from .models import Project


def require_project(
    db: Session, project_id: str, user_id: str, writable: bool = False, lock: bool = False
) -> Project:
    """按拥有者获取项目；写操作对项目行加锁并拒绝归档/删除。"""
    query = select(Project).where(
        Project.id == project_id,
        Project.owner_user_id == user_id,
        Project.lifecycle.not_in(["deleting", "deleted"]),
    )
    if writable or lock:
        query = query.with_for_update()
    project = db.scalar(query)
    if project is None:
        raise DomainError("NOT_FOUND", "项目不存在或不可访问", 404)
    if writable and project.lifecycle != "active":
        raise DomainError("PROJECT_ARCHIVED", "请先恢复归档项目")
    return project

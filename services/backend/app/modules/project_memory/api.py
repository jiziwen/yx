"""仅用户显式确认可写项目记忆，Agent 工具不挂载该写入口。"""

from fastapi import APIRouter, Request

from app.core.security import DB, UserDep
from app.modules.projects.service import require_project

from .schemas import MemoryInput, MemoryView
from .service import confirm_memory, memory_view

router = APIRouter(tags=["project-memory"])


@router.get("/api/v1/web/projects/{project_id}/memory", response_model=MemoryView)
def get_memory(project_id: str, user: UserDep, db: DB, request: Request):
    """拥有者可查看当前有效记忆。"""
    return memory_view(request.app, db, require_project(db, project_id, user.id))


@router.put("/api/v1/web/projects/{project_id}/memory", response_model=MemoryView)
def put_memory(project_id: str, body: MemoryInput, user: UserDep, db: DB, request: Request):
    """确认、编辑、清空均为显式用户请求；不修改生成授权或已冻结方案。"""
    project = require_project(db, project_id, user.id, writable=True)
    return confirm_memory(request.app, db, project, user.id, body)

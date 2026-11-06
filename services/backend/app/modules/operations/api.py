"""管理接口：独立身份校验，默认只看脱敏事实，不提供用户照片。"""

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core.security import DB, AdminDep, StaffDep
from app.modules.catalog.live import current_catalog
from app.modules.identity.models import User
from app.modules.media_jobs.models import Job
from app.modules.projects.models import Project

from .entitlements import router as entitlements_router
from .jobs import router as job_router
from .model_calls import router as model_calls_router
from .model_settings import router as model_settings_router
from .models import Audit
from .schemas import AdminJobView, AdminUserView, AuditView, InventoryView, OverviewView
from .theme_materials import router as theme_materials_router

router = APIRouter(tags=["operations"])
router.include_router(entitlements_router)
router.include_router(theme_materials_router)
router.include_router(job_router)
router.include_router(model_settings_router)
router.include_router(model_calls_router)


@router.get("/api/v1/admin/overview", response_model=OverviewView)
def overview(user: AdminDep, db: DB):
    """运营统计来自数据库；未采集的成本不填造假数值。"""
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {
        "users": db.scalar(select(func.count()).select_from(User).where(User.role == "customer")),
        "projects": db.scalar(select(func.count()).select_from(Project)),
        "jobs": counts,
        "estimated_cost": None,
        "phase": "M0 / M1 development",
    }


@router.get("/api/v1/admin/catalog", response_model=InventoryView)
def admin_catalog(request: Request, user: StaffDep):
    """展示启动时生效的模块、开关和网关能力，不暴露密钥与供应商 URL。"""
    state = request.app.state
    return {
        "catalog": current_catalog(request.app),
        "features": state.config["features"],
        "modules": [{"id": m.id, "version": m.version, "requires": m.requires} for m in state.modules],
        "providers": state.gateway.public_inventory(),
    }


@router.get("/api/v1/admin/jobs", response_model=list[AdminJobView])
def jobs(user: AdminDep, db: DB):
    """只读元信息，待核对任务不提供盲目重试按钮。"""
    return [
        {
            "id": j.id,
            "project_id": j.project_id,
            "status": j.status,
            "provider_id": j.provider_id,
            "error_code": j.error_code,
            "created_at": j.created_at,
        }
        for j in db.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))
    ]


@router.get("/api/v1/admin/users", response_model=list[AdminUserView])
def users(user: AdminDep, db: DB):
    """用户列表不包含手机号摘要或照片访问入口。"""
    return [
        {
            "id": u.id,
            "display_name": u.display_name,
            "role": u.role,
            "status": u.status,
            "created_at": u.created_at,
        }
        for u in db.scalars(select(User).order_by(User.created_at.desc()).limit(100))
    ]


@router.get("/api/v1/admin/audit", response_model=list[AuditView])
def audits(user: AdminDep, db: DB):
    """审计摘要不含原始文件、聊天或供应商正文。"""
    return [
        {
            "id": a.id,
            "actor_id": a.actor_id,
            "action": a.action,
            "resource_id": a.resource_id,
            "summary": a.summary,
            "created_at": a.created_at,
        }
        for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(100))
    ]

"""任务快照和取消入口；不将浏览器请求作为供应商执行状态。"""

from fastapi import APIRouter
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.security import DB, UserDep
from app.core.views import AssetView, JobView
from app.modules.assets.models import Asset
from app.modules.assets.service import assert_accessible
from app.modules.projects.service import require_project

from .models import Job
from .service import cancel

router = APIRouter(tags=["media_jobs"])


@router.get("/api/v1/web/projects/{project_id}/jobs", response_model=list[JobView])
def jobs(project_id: str, user: UserDep, db: DB):
    """按创建时间返回项目任务，前端仅对活跃任务轮询。"""
    require_project(db, project_id, user.id)
    return list(
        db.scalars(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc(), Job.item_index)
            .limit(100)
        )
    )


@router.post("/api/v1/web/jobs/{job_id}/cancel", response_model=JobView)
def cancel_job(job_id: str, user: UserDep, db: DB):
    """重试不会重复返还权益。"""
    job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise DomainError("NOT_FOUND", "任务不可访问", 404)
    require_project(db, job.project_id, user.id)
    cancel(db, job)
    db.commit()
    return job


@router.get("/api/v1/web/projects/{project_id}/works", response_model=list[AssetView])
def works(project_id: str, user: UserDep, db: DB):
    """只交付 ready 且当前输入授权仍有效的主图。"""
    require_project(db, project_id, user.id)
    result = []
    for asset in db.scalars(
        select(Asset)
        .where(Asset.project_id == project_id, Asset.kind == "photo", Asset.status == "ready")
        .order_by(Asset.created_at.desc())
    ):
        try:
            assert_accessible(db, asset)
            result.append(asset)
        except DomainError:
            continue
    return result

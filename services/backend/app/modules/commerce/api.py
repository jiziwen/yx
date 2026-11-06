"""权益入口；试用按账户活动唯一，所有金额/次数由服务端决定。"""

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.security import DB, UserDep
from app.core.views import AccountView
from app.modules.projects.service import require_project

from .models import Account, EntitlementEvent

router = APIRouter(tags=["commerce"])


@router.get("/api/v1/web/projects/{project_id}/entitlements", response_model=AccountView)
def entitlements(project_id: str, user: UserDep, db: DB):
    """仅返回拥有者项目的权益。"""
    require_project(db, project_id, user.id)
    return db.scalar(select(Account).where(Account.project_id == project_id, Account.kind == "photo"))


@router.post("/api/v1/web/projects/{project_id}/trial-grants", response_model=AccountView)
def grant_trial(project_id: str, request: Request, user: UserDep, db: DB):
    """同一账号同一活动全项目只领取一次，不可通过新建项目刷权益。"""
    config = request.app.state.config
    if not config["features"].get("trial_enabled", False):
        raise DomainError("TRIAL_UNAVAILABLE", "试用活动暂未开放", 403)
    require_project(db, project_id, user.id, writable=True)
    event_key = f"trial:{config['trial']['version']}:{user.id}"
    existing = db.scalar(select(EntitlementEvent).where(EntitlementEvent.event_key == event_key))
    account = db.scalar(
        select(Account).where(Account.project_id == project_id, Account.kind == "photo").with_for_update()
    )
    if existing:
        if existing.account_id == account.id:
            return account
        raise DomainError("TRIAL_ALREADY_CLAIMED", "这个账号已在其他项目领取过本期试用")
    count = config["trial"]["photo_count"]
    account.available += count
    db.add(
        EntitlementEvent(
            account_id=account.id, event_key=event_key, kind="grant", amount=count, reason="账号内测试用"
        )
    )
    db.commit()
    return account

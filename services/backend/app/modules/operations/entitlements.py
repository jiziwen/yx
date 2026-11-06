"""管理员人工补发次数；权益、流水和审计同事务落库，重复请求不重复发放。"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.core.db import uid
from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, AdminDep
from app.core.views import AccountView, View
from app.modules.commerce.models import Account, EntitlementEvent
from app.modules.identity.models import User
from app.modules.projects.models import Project
from app.modules.projects.service import require_project

from .models import Audit

router = APIRouter(tags=["admin-entitlements"])
ACTION = "entitlements.grant"


class GrantInput(Input):
    """发放仅接受正整数与非空原因；请求键标识一次明确的管理员动作。"""

    request_key: UUID
    user_id: str = Field(min_length=1, max_length=36)
    project_id: str = Field(min_length=1, max_length=36)
    amount: int = Field(strict=True, ge=1, le=10000)
    reason: str = Field(min_length=1, max_length=120)


class GrantUser(View):
    """只公开可发放客户的昵称与ID，不提供手机号或登录摘要。"""

    id: str
    display_name: str


class GrantUsers(View):
    """可搜索、分页的用户选择列表。"""

    items: list[GrantUser]
    total: int


class GrantProject(View):
    """项目选择展示当前三桶权益；只列出所选用户的有效项目。"""

    id: str
    title: str
    account: AccountView


class GrantProjects(View):
    """用户项目分页结果。"""

    items: list[GrantProject]
    total: int


class GrantRecord(View):
    """发放事实与操作者，余额为当次发放后的历史快照。"""

    id: str
    user_id: str
    user_name: str
    project_id: str
    project_title: str
    amount: int
    reason: str
    source: str
    actor_id: str | None
    actor_name: str | None
    available_after: int | None
    created_at: datetime


class GrantRecords(View):
    """人工补发及账号试用流水的分页结果。"""

    items: list[GrantRecord]
    total: int


def record_query():
    """复用只读关联，旧试用流水没有人工操作者和余额快照。"""
    actor = aliased(User)
    return (
        select(EntitlementEvent, Account, Project, User, Audit, actor)
        .join(Account, Account.id == EntitlementEvent.account_id)
        .join(Project, Project.id == Account.project_id)
        .join(User, User.id == Project.owner_user_id)
        .outerjoin(Audit, (Audit.resource_id == EntitlementEvent.id) & (Audit.action == ACTION))
        .outerjoin(actor, actor.id == Audit.actor_id)
        .where(EntitlementEvent.kind == "grant")
    )


def record_view(row):
    """历史名称从当前资源读取，删除匿名化后不重新公开原名称。"""
    event, account, project, customer, audit, actor = row
    return {
        "id": event.id,
        "user_id": customer.id,
        "user_name": customer.display_name,
        "project_id": project.id,
        "project_title": project.title,
        "amount": event.amount,
        "reason": event.reason,
        "source": "manual" if audit else "trial",
        "actor_id": actor.id if actor else None,
        "actor_name": actor.display_name if actor else None,
        "available_after": audit.summary.get("available_after") if audit else None,
        "created_at": event.created_at,
    }


@router.get("/api/v1/admin/entitlements/users", response_model=GrantUsers)
def grant_users(
    user: AdminDep,
    db: DB,
    q: str = Query(default="", max_length=80),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    """搜索客户昵称或完整/部分ID；不要求运营取得手机号。"""
    filters = [User.role == "customer", User.status == "active"]
    if q.strip():
        filters.append(
            or_(
                User.id.contains(q.strip(), autoescape=True),
                User.display_name.contains(q.strip(), autoescape=True),
            )
        )
    return {
        "items": list(
            db.scalars(
                select(User)
                .where(*filters)
                .order_by(User.created_at.desc(), User.id)
                .offset(offset)
                .limit(limit)
            )
        ),
        "total": db.scalar(select(func.count()).select_from(User).where(*filters)),
    }


@router.get("/api/v1/admin/entitlements/users/{user_id}/projects", response_model=GrantProjects)
def grant_projects(
    user_id: str,
    user: AdminDep,
    db: DB,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    """项目列表和服务端提交都检查用户归属，防止切换用户后误发旧项目。"""
    customer = db.get(User, user_id)
    if not customer or customer.role != "customer" or customer.status != "active":
        raise DomainError("NOT_FOUND", "客户不存在或不可发放", 404)
    filters = [Project.owner_user_id == user_id, Project.lifecycle == "active", Account.kind == "photo"]
    rows = db.execute(
        select(Project, Account)
        .join(Account, Account.project_id == Project.id)
        .where(*filters)
        .order_by(Project.created_at.desc(), Project.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [
            {"id": project.id, "title": project.title, "account": account} for project, account in rows
        ],
        "total": db.scalar(
            select(func.count())
            .select_from(Project)
            .join(Account, Account.project_id == Project.id)
            .where(*filters)
        ),
    }


@router.get("/api/v1/admin/entitlements/grants", response_model=GrantRecords)
def grant_records(
    user: AdminDep,
    db: DB,
    user_id: str | None = None,
    project_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    """可按用户/项目核对发放流水；不修改可用、预占或已用次数。"""
    query = record_query()
    if user_id:
        query = query.where(Project.owner_user_id == user_id)
    if project_id:
        query = query.where(Project.id == project_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(EntitlementEvent.created_at.desc(), EntitlementEvent.id).offset(offset).limit(limit)
    )
    return {"items": [record_view(row) for row in rows], "total": total}


@router.post("/api/v1/admin/entitlements/grants", response_model=GrantRecord)
def grant_entitlements(body: GrantInput, user: AdminDep, db: DB):
    """按管理员→客户→项目→权益加锁；提交失败一起回滚，不碰预占和已用桶。"""
    # 串行同一管理员的请求键检查；不同管理员仍由目标客户/权益行锁保护相加。
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    key = f"manual:{user.id}:{body.request_key}"
    existing = db.scalar(select(EntitlementEvent).where(EntitlementEvent.event_key == key))
    payload = body.model_dump(mode="json", exclude={"request_key"})
    if existing:
        row = db.execute(record_query().where(EntitlementEvent.id == existing.id)).one()
        audit = row[4]
        if not audit or audit.summary.get("request") != payload:
            raise DomainError("IDEMPOTENCY_CONFLICT", "本次发放请求内容已改变，请核对记录后发起新发放")
        return record_view(row)
    customer = db.scalar(select(User).where(User.id == body.user_id).with_for_update())
    if not customer or customer.role != "customer" or customer.status != "active":
        raise DomainError("NOT_FOUND", "客户不存在或不可发放", 404)
    project = require_project(db, body.project_id, customer.id, writable=True)
    account = db.scalar(
        select(Account).where(Account.project_id == project.id, Account.kind == "photo").with_for_update()
    )
    if account is None:
        raise DomainError("NOT_FOUND", "项目权益账户不存在", 404)
    before = account.available
    account.available += body.amount
    event = EntitlementEvent(
        id=uid(), account_id=account.id, event_key=key, kind="grant", amount=body.amount, reason=body.reason
    )
    db.add(event)
    db.add(
        Audit(
            actor_id=user.id,
            action=ACTION,
            resource_id=event.id,
            summary={"request": payload, "available_before": before, "available_after": account.available},
        )
    )
    db.flush()
    result = record_view(db.execute(record_query().where(EntitlementEvent.id == event.id)).one())
    db.commit()
    return result

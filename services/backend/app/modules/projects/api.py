"""项目和人物 API；拥有者、需求修订和隐私授权在服务端校验。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Header
from pydantic import Field
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, UserDep
from app.core.views import ProjectView, SubjectView
from app.modules.commerce.models import Account
from app.modules.operations.models import Audit
from app.modules.project_memory.retention import KeepPreferences, retain_preferences, selected_preferences

from .models import Project, Subject
from .service import require_project

router = APIRouter(tags=["projects"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=100)]


class CreateProject(Input):
    """项目创建参数；界面主题不属于生成规格。"""

    title: str = Field(min_length=1, max_length=120)
    kind: Literal["wedding", "portrait"]


class UpdateProject(Input):
    """乐观版本控制，避免多页签静默覆盖。"""

    title: str = Field(min_length=1, max_length=120)
    lifecycle: Literal["active", "archived"]
    expected_revision: int = Field(ge=1)


class CreateSubject(Input):
    """调用者必须显式同意人物使用声明。"""

    subject_key: Literal["person_a", "person_b"]
    display_name: str = Field(min_length=1, max_length=80)
    declared: Literal[True]


@router.get("/api/v1/web/projects", response_model=list[ProjectView])
def list_projects(user: UserDep, db: DB, limit: int = 50):
    """列表有界，排除删除中的项目。"""
    return list(
        db.scalars(
            select(Project)
            .where(Project.owner_user_id == user.id, Project.lifecycle.not_in(["deleted", "deleting"]))
            .order_by(Project.created_at.desc())
            .limit(min(max(limit, 1), 100))
        )
    )


@router.post("/api/v1/web/projects", response_model=ProjectView, status_code=201)
def create_project(body: CreateProject, key: Key, user: UserDep, db: DB):
    """同一个创建键同内容返回原项目，不同内容拒绝。"""
    existing = db.scalar(
        select(Project).where(Project.owner_user_id == user.id, Project.client_request_key == key)
    )
    if existing:
        if (existing.title, existing.kind) != (body.title, body.kind):
            raise DomainError("IDEMPOTENCY_CONFLICT", "该请求键已用于其他项目")
        return existing
    project = Project(owner_user_id=user.id, client_request_key=key, **body.model_dump())
    db.add(project)
    db.flush()
    db.add(Account(project_id=project.id))
    db.commit()
    return project


@router.get("/api/v1/web/projects/{project_id}", response_model=ProjectView)
def get_project(project_id: str, user: UserDep, db: DB):
    """项目权威快照，不依赖浏览器保留状态。"""
    return require_project(db, project_id, user.id)


@router.patch("/api/v1/web/projects/{project_id}", response_model=ProjectView)
def update_project(project_id: str, body: UpdateProject, user: UserDep, db: DB):
    """归档和重命名都要求当前版本，归档不删除任务。"""
    project = require_project(db, project_id, user.id, lock=True)
    if project.brief_revision != body.expected_revision:
        raise DomainError("REVISION_CONFLICT", "项目已更新，请刷新")
    project.title, project.lifecycle = body.title, body.lifecycle
    project.brief_revision += 1
    db.commit()
    return project


@router.get("/api/v1/web/projects/{project_id}/subjects", response_model=list[SubjectView])
def subjects(project_id: str, user: UserDep, db: DB):
    """人物归属经项目权限过滤。"""
    require_project(db, project_id, user.id)
    return list(db.scalars(select(Subject).where(Subject.project_id == project_id)))


@router.post("/api/v1/web/projects/{project_id}/subjects", response_model=SubjectView)
def add_subject(project_id: str, body: CreateSubject, user: UserDep, db: DB):
    """单人写真只允许 person_a；不允许重复人物槽。"""
    project = require_project(db, project_id, user.id, writable=True)
    if project.kind == "portrait" and body.subject_key != "person_a":
        raise DomainError("SUBJECT_LIMIT", "写真项目仅支持一个人物", 422)
    if db.scalar(
        select(Subject).where(Subject.project_id == project_id, Subject.subject_key == body.subject_key)
    ):
        raise DomainError("SUBJECT_EXISTS", "该人物槽已存在")
    subject = Subject(project_id=project_id, subject_key=body.subject_key, display_name=body.display_name)
    db.add(subject)
    project.brief_revision += 1
    db.commit()
    return subject


@router.post("/api/v1/web/subjects/{subject_id}/revoke")
def revoke_subject(subject_id: str, user: UserDep, db: DB, body: KeepPreferences | None = None):
    """先持久化撤销与访问屏障，清理由独立维护进程重试。"""
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise DomainError("NOT_FOUND", "人物不可访问", 404)
    project = require_project(db, subject.project_id, user.id, lock=True)
    selected = selected_preferences(db, project, body)
    if subject.authorization_state != "revoked":
        subject.authorization_state = "revoked"
        subject.authorization_revision += 1
        project.privacy_epoch += 1
        project.brief_revision += 1
        retain_preferences(db, project, user.id, selected)
        db.add(
            Audit(
                actor_id=user.id,
                action="subject.revoke",
                resource_id=subject.id,
                summary={"privacy_epoch": project.privacy_epoch},
            )
        )
    db.commit()
    return {"ok": True, "cleanup": "pending"}

"""模型候选、证据审核及启用；后台保存不再隐式切换线上模型。"""

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.schemas import Input
from app.core.security import DB, AdminDep
from app.modules.agents.context import fingerprint
from app.modules.catalog.live import current_catalog

from .model_schemas import ModelSettingsInput
from .model_settings import compile_providers, publish_settings, settings_view
from .models import Audit, ModelCandidate

router = APIRouter(tags=["model-candidates"])


class CandidateApproval(Input):
    """审核记录必须绑定候选和全部启用能力，不接受只有一个批准标签。"""

    expected_revision: int = Field(ge=0)
    candidate_digest: str = Field(min_length=64, max_length=64)
    confirmed: bool
    cases: dict[str, str] = Field(min_length=1, max_length=10)
    actual_cost_cny: float = Field(ge=0, le=100000)
    bill_reference: str = Field(min_length=3, max_length=300)
    review_note: str = Field(min_length=3, max_length=1000)


def candidate_digest(app, settings, providers, routes):
    """模型证据同时绑定当前执行代码和目录，变更后不能沿用旧批准。"""
    from hashlib import sha256

    from app.core.config import ROOT
    from app.modules.agents.releases import code_files

    return fingerprint(
        {
            "settings": settings,
            "providers": providers,
            "routes": routes,
            "code": {
                str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in code_files()
            },
            "catalog": {key: value for key, value in current_catalog(app).items() if not key.startswith("_")},
        }
    )


def required_cases(settings):
    """审核覆盖实际开放的操作、人物范围和输入上限；单人证据不代表双人。"""
    expected = set()
    if settings.image.enabled:
        expected |= {"image:" + operation for operation in settings.image.operations}
        expected.add("image:input-limits")
        if "reference" in settings.image.operations or "edit" in settings.image.operations:
            expected |= {"image:subjects:" + str(n) for n in range(1, settings.image.max_subjects + 1)}
        if "edit" in settings.image.operations and settings.image.max_subjects:
            expected.add("image:template")
    if settings.llm.enabled:
        expected.add("llm")
    if settings.vision.enabled:
        expected.add("vision")
    return expected or {"disabled-routes"}


def view(row):
    """只公开非敏感配置和证据，不存密钥或图片正文。"""
    return {
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "digest",
                "status",
                "settings_json",
                "evidence_json",
                "approved_by",
                "release_id",
            )
        },
        "required_cases": sorted(
            required_cases(ModelSettingsInput(expected_revision=0, **row.settings_json))
        ),
    }


@router.get("/api/v1/admin/model-candidates")
def list_candidates(user: AdminDep, db: DB):
    """有界审核历史，原始候选不会被覆盖。"""
    return [
        view(row)
        for row in db.scalars(select(ModelCandidate).order_by(ModelCandidate.created_at.desc()).limit(50))
    ]


@router.post("/api/v1/admin/model-candidates", status_code=201)
def save_candidate(body: ModelSettingsInput, user: AdminDep, db: DB, request: Request):
    """编译仅检查配置，不调用供应商、不改指针。"""
    profile = body.model_dump(exclude={"expected_revision"})
    providers, routes = compile_providers(request.app, body)
    row = ModelCandidate(
        actor_id=user.id,
        settings_json=profile,
        digest=candidate_digest(request.app, profile, providers, routes),
    )
    db.add(row)
    db.commit()
    return view(row)


@router.post("/api/v1/admin/model-candidates/{candidate_id}/activate")
def activate(candidate_id: str, body: CandidateApproval, user: AdminDep, db: DB, request: Request):
    """人工提交逐能力证据后才发布；可重新启用历史候选作为显式回退。"""
    row = db.scalar(select(ModelCandidate).where(ModelCandidate.id == candidate_id).with_for_update())
    if row is None:
        raise DomainError("NOT_FOUND", "候选不存在", 404)
    settings = ModelSettingsInput(expected_revision=body.expected_revision, **row.settings_json)
    providers, routes = compile_providers(request.app, settings)
    digest = candidate_digest(request.app, row.settings_json, providers, routes)
    expected = required_cases(settings)
    if (
        not body.confirmed
        or body.candidate_digest != row.digest
        or digest != row.digest
        or set(body.cases) != expected
        or any(len(value.strip()) < 3 for value in body.cases.values())
    ):
        raise DomainError("MODEL_EVIDENCE_REQUIRED", "请提交匹配候选的全部能力实测记录并明确批准", 422)
    # 审核和发布共用同一事务，publish_settings负责最终提交。
    row.evidence_json = body.model_dump()
    row.status, row.approved_by = "approved", user.id
    db.add(
        Audit(
            actor_id=user.id,
            action="model_candidate.approve",
            resource_id=row.id,
            summary={"digest": row.digest, "capabilities": sorted(expected)},
        )
    )
    result = publish_settings(request.app, db, user.id, settings, approved=True)
    from .models import ModelSettingHead

    row.release_id = db.get(ModelSettingHead, "ai302").release_id
    db.commit()
    return {**result, "candidate": view(row), "active": settings_view(request.app, db)}

"""模型调用只读管理 API；图片任务合并分页，实际请求明细按需读取。"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import defer

from app.core.db import now
from app.core.errors import DomainError
from app.core.security import DB, AdminDep
from app.core.views import View
from app.integrations.call_logging import visible_payload
from app.modules.operations.models import Audit, ModelCall

router = APIRouter()
PAGE_SIZE = 20


class ModelCallView(View):
    """单次操作元信息；running表示尚无最终记录，不代表远端成功。"""

    id: str
    created_at: datetime
    provider_id: str
    kind: str
    model: str
    operation: str
    status: str
    development_sample: bool
    project_id: str | None
    owner_user_id: str | None
    run_id: str | None
    job_id: str | None
    finished_at: datetime | None
    latency_ms: int | None
    http_status: int | None
    error_code: str | None
    result_unknown: bool


class ModelCallSummary(ModelCallView):
    """同一图片任务和冻结供应商合并；耗时为各次操作累计耗时。"""

    call_count: int
    lookup_count: int
    latest_at: datetime
    latest_operation: str


class ModelCallPage(View):
    """先合并再固定分页，客户端不能扩大每页数量。"""

    items: list[ModelCallSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class ModelCallPayload(ModelCallView):
    """仅管理员按条读取已脱敏有界正文。"""

    request: Any
    response: Any
    scrubbed: bool


class ModelCallDetail(ModelCallSummary):
    """默认展示原始提交入参和最近出参；每次操作仍可独立核查。"""

    request: Any
    response: Any
    scrubbed: bool
    request_call_id: str
    response_call_id: str
    calls: list[ModelCallView]
    calls_page: int
    calls_total_pages: int


def metadata_query():
    """列表与明细索引不加载请求/响应正文。"""
    return select(ModelCall).options(defer(ModelCall.request_json), defer(ModelCall.response_json))


def group_conditions(row):
    """一个图片Job冻结一个模型；不按模型名跨任务或跨隐私代次混合正文。"""
    if row.kind != "image" or not row.job_id:
        return [ModelCall.id == row.id]
    return [
        ModelCall.kind == "image",
        ModelCall.job_id == row.job_id,
        ModelCall.provider_id == row.provider_id,
        ModelCall.project_id == row.project_id,
        ModelCall.owner_user_id == row.owner_user_id,
        ModelCall.privacy_epoch == row.privacy_epoch,
    ]


def ranked_calls(conditions=()):
    """数据库内合并历史记录，计数及分页均以合并后的任务为单位。"""
    group_key = case(
        (ModelCall.kind == "image", func.coalesce(ModelCall.job_id, ModelCall.id)),
        else_=ModelCall.id,
    )
    partition = [
        group_key,
        ModelCall.job_id.is_not(None),
        ModelCall.kind,
        ModelCall.provider_id,
        ModelCall.project_id,
        ModelCall.owner_user_id,
        ModelCall.privacy_epoch,
    ]
    ascending = [ModelCall.created_at.asc(), ModelCall.id.asc()]
    descending = [ModelCall.created_at.desc(), ModelCall.id.desc()]
    return (
        select(
            ModelCall.id,
            func.row_number().over(partition_by=partition, order_by=ascending).label("position"),
            func.first_value(ModelCall.id)
            .over(partition_by=partition, order_by=descending)
            .label("latest_id"),
            func.max(ModelCall.created_at).over(partition_by=partition).label("latest_at"),
            func.count().over(partition_by=partition).label("call_count"),
            func.sum(case((ModelCall.operation == "lookup", 1), else_=0))
            .over(partition_by=partition)
            .label("lookup_count"),
            func.sum(ModelCall.latency_ms).over(partition_by=partition).label("latency_ms"),
        )
        .where(*conditions)
        .subquery()
    )


def summary(db, aggregate, records=None):
    """保留最初调用标识与模型，以最近操作表示HTTP状态。"""
    if records is None:
        records = {
            row.id: row
            for row in db.scalars(
                metadata_query().where(ModelCall.id.in_([aggregate.id, aggregate.latest_id]))
            )
        }
    first, latest = records[aggregate.id], records[aggregate.latest_id]
    body = ModelCallView.model_validate(first).model_dump()
    for field in ("status", "http_status", "error_code", "result_unknown", "finished_at"):
        body[field] = getattr(latest, field)
    body.update(
        call_count=aggregate.call_count,
        lookup_count=aggregate.lookup_count,
        latest_at=aggregate.latest_at,
        latest_operation=latest.operation,
        latency_ms=aggregate.latency_ms,
    )
    return body


def payload(db, row):
    """每次读取分别校验授权，晚到回包和旧隐私代次不可恢复正文。"""
    allowed = visible_payload(db, row)
    return {
        "request": row.request_json if allowed else {"scrubbed": True},
        "response": row.response_json if allowed else {"scrubbed": True},
        "scrubbed": not allowed
        or bool(isinstance(row.request_json, dict) and row.request_json.get("scrubbed")),
    }


def audit_read(db, user, row, **extra):
    """只审计读取标识，不复制模型正文。"""
    db.add(
        Audit(
            actor_id=user.id,
            action="model_call.read",
            resource_id=row.id,
            summary={"viewed_at": now().isoformat(), **extra},
        )
    )
    db.commit()


@router.get("/api/v1/admin/model-calls", response_model=ModelCallPage)
def list_calls(user: AdminDep, db: DB, page: int = Query(1, ge=1, le=1_000_000)):
    """同任务图片轮询合并为一行；无任务标识的调用逐条保留。"""
    ranked = ranked_calls()
    groups = select(ranked).where(ranked.c.position == 1)
    total = db.scalar(select(func.count()).select_from(groups.subquery()))
    aggregates = db.execute(
        groups.order_by(ranked.c.latest_at.desc(), ranked.c.latest_id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    ids = {item for row in aggregates for item in (row.id, row.latest_id)}
    records = {row.id: row for row in db.scalars(metadata_query().where(ModelCall.id.in_(ids)))}
    return {
        "items": [summary(db, row, records) for row in aggregates],
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": (total + PAGE_SIZE - 1) // PAGE_SIZE,
    }


@router.get("/api/v1/admin/model-calls/{call_id}", response_model=ModelCallDetail)
def call_detail(
    call_id: str,
    user: AdminDep,
    db: DB,
    calls_page: int = Query(1, ge=1, le=1_000_000),
):
    """旧查询记录也可定位原始提交；各次明细固定20条分页且正文按需读。"""
    row = db.scalar(metadata_query().where(ModelCall.id == call_id))
    if row is None:
        raise DomainError("NOT_FOUND", "调用记录不存在", 404)
    conditions = group_conditions(row)
    ranked = ranked_calls(conditions)
    aggregate = db.execute(select(ranked).where(ranked.c.position == 1)).one()
    body = summary(db, aggregate)
    first = db.get(ModelCall, aggregate.id)
    latest = db.get(ModelCall, aggregate.latest_id)
    request_body, response_body = payload(db, first), payload(db, latest)
    calls = list(
        db.scalars(
            metadata_query()
            .where(*conditions)
            .order_by(ModelCall.created_at.desc(), ModelCall.id.desc())
            .offset((calls_page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )
    body.update(
        request=request_body["request"],
        response=response_body["response"],
        scrubbed=request_body["scrubbed"] or response_body["scrubbed"],
        request_call_id=first.id,
        response_call_id=latest.id,
        calls=[ModelCallView.model_validate(call) for call in calls],
        calls_page=calls_page,
        calls_total_pages=(aggregate.call_count + PAGE_SIZE - 1) // PAGE_SIZE,
    )
    audit_read(db, user, row, request_call_id=first.id, response_call_id=latest.id, calls_page=calls_page)
    return body


@router.get("/api/v1/admin/model-calls/{call_id}/payload", response_model=ModelCallPayload)
def call_payload(call_id: str, user: AdminDep, db: DB):
    """读取某一次提交或查询的实际入出参，保留失败和中间结果。"""
    row = db.get(ModelCall, call_id)
    if row is None:
        raise DomainError("NOT_FOUND", "调用记录不存在", 404)
    body = ModelCallView.model_validate(row).model_dump()
    body.update(payload(db, row))
    audit_read(db, user, row)
    return body

"""只读插件注册与数据库保护；身份注入、参数白名单、结果有界且不返回上游正文。"""

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.core.plugins import load_symbol
from app.core.schemas import Input
from app.core.views import View
from app.modules.commerce.models import Account
from app.modules.identity.models import User
from app.modules.media_jobs.models import Job
from app.modules.projects.service import require_project

STATUS_LABELS = {
    "queued": "排队中",
    "running": "创作中",
    "succeeded": "已完成",
    "failed": "未完成",
    "cancel_requested": "取消处理中",
    "cancelled": "已取消",
    "reconciliation_required": "待核对，次数仍预占",
}
FAILURES = {
    "PROVIDER_AUTH_FAILED": "供应商凭证无效或已过期，请检查后台凭证配置。",
    "PROVIDER_BALANCE_INSUFFICIENT": "供应商账户余额不足。",
    "PROVIDER_PERMISSION_DENIED": "供应商未授予当前模型的访问权限。",
    "PROVIDER_MODEL_UNAVAILABLE": "供应商模型或接口不可用，请检查后台模型配置。",
    "PROVIDER_INVALID_REQUEST": "供应商不接受当前请求参数，请检查模型接口配置。",
    "PROVIDER_REJECTED": "供应商拒绝了请求，未提供更具体的公开原因。",
    "PROVIDER_TASK_FAILED": "供应商报告任务失败，未提供更具体的公开原因。",
    "PROVIDER_RATE_LIMITED": "供应商暂时限流。",
    "PROVIDER_RESULT_UNKNOWN": "供应商执行结果尚未确认，不能认定失败或自动重发。",
    "PROVIDER_STATUS_UNKNOWN": "暂未取得可信的供应商状态，需要继续核对。",
    "WORKER_INTERRUPTED": "执行进程中断，外部结果需要核对。",
    "AUTHORIZATION_CHANGED": "人物或素材授权已变化。",
    "INPUT_UNAVAILABLE": "所需输入素材已不可用。",
    "PROVIDER_CONFIG_CHANGED": "冻结的模型配置已不可用或发生变化。",
    "PROVIDER_INVALID_OUTPUT": "供应商返回的结果未通过校验。",
}


@dataclass(frozen=True)
class ToolScope:
    """只由服务器从 Run/项目解析，不接受模型的身份与资源范围。"""

    user_id: str
    project_id: str | None
    privacy_epoch: int
    role: str = "creative"


class NoArguments(Input):
    """当前项目的无参数查询，额外身份字段一律拒绝。"""


class QuotaResult(View):
    """查询观察时刻的三个权益桶，不构成价格、退款或生成授权。"""

    available: int
    reserved: int
    consumed: int
    unit: str = "次"


class JobArguments(Input):
    """可选指定当前项目任务，否则查询最近五项及全项目状态计数。"""

    job_id: str | None = Field(default=None, min_length=1, max_length=36)


class JobFact(View):
    """只读公开任务事实；不包含供应商凭据、响应、输入或下载链接。"""

    id: str
    item_index: int
    status: str
    status_label: str
    revision: int
    created_at: datetime
    error_code: str | None
    reason: str | None


class JobsResult(View):
    """有界详情加状态分布，不虚构图片生成百分比或预计时间。"""

    total: int
    counts: dict[str, int]
    jobs: list[JobFact]
    recent_limit: int = 5


class EntitlementsTool:
    """只读当前项目可用/预占/已用次数。"""

    name, version, title = "get_entitlements", "1", "查询创作次数"
    role, roles, scope, read_only = "creative", ("creative", "support"), "current_project", True
    requires = ("commerce",)
    input_model, output_model = NoArguments, QuotaResult

    def read(self, app, db, scope, arguments):
        """只读账户，决不领取、预占、退款或更改次数。"""
        account = db.scalar(
            select(Account).where(Account.project_id == scope.project_id, Account.kind == "photo")
        )
        if account is None:
            raise DomainError("TOOL_NOT_FOUND", "项目次数暂不可查询", 404)
        return {"available": account.available, "reserved": account.reserved, "consumed": account.consumed}


class JobStatusTool:
    """只读当前项目进度及公开失败分类。"""

    name, version, title = "get_job_status", "1", "查询生成进度与失败原因"
    role, roles, scope, read_only = "creative", ("creative", "support"), "current_project", True
    requires = ("media_jobs",)
    input_model, output_model = JobArguments, JobsResult

    def read(self, app, db, scope, arguments):
        """从业务 Job 状态读取，不直接查询供应商，不触发重试或结算。"""
        query = select(Job).where(Job.project_id == scope.project_id)
        if arguments.job_id:
            query = query.where(Job.id == arguments.job_id)
        jobs = list(db.scalars(query.order_by(Job.created_at.desc(), Job.item_index).limit(5)))
        if arguments.job_id and not jobs:
            raise DomainError("TOOL_NOT_FOUND", "任务不存在或不可访问", 404)
        rows = list(
            db.execute(
                select(Job.status, func.count())
                .where(Job.project_id == scope.project_id)
                .group_by(Job.status)
            )
        )
        facts = []
        for job in jobs:
            reason = None
            if job.error_code:
                reason = FAILURES.get(job.error_code, "任务记录了未公开的错误分类，当前无法确定更具体原因。")
            elif job.status == "failed":
                reason = "任务未完成，记录中没有更具体的公开原因。"
            elif job.status == "reconciliation_required":
                reason = "外部结果尚未确认，次数继续预占，请等待核对。"
            facts.append(
                {
                    "id": job.id,
                    "item_index": job.item_index,
                    "status": job.status,
                    "status_label": STATUS_LABELS.get(job.status, "状态待确认"),
                    "revision": job.revision,
                    "created_at": job.created_at,
                    "error_code": job.error_code if job.error_code in FAILURES else None,
                    "reason": reason,
                }
            )
        return {"total": sum(count for _, count in rows), "counts": dict(rows), "jobs": facts}


class ReadToolRegistry:
    """只装配可信配置中的无副作用插件；关闭或越权名称无法被调用。"""

    def __init__(self, configurations):
        """启动验证名称、权限和输入/输出契约，配置错误不静默降级。"""
        self.entries = {}
        for config in configurations:
            if not config["enabled"]:
                continue
            tool = load_symbol(config["entrypoint"])()
            if (
                config["name"] in self.entries
                or tool.name != config["name"]
                or tool.read_only is not True
                or not set(getattr(tool, "roles", (tool.role,))).issubset({"creative", "support"})
                or tool.scope not in {"current_project", "published_knowledge"}
                or not issubclass(tool.input_model, BaseModel)
                or not issubclass(tool.output_model, BaseModel)
            ):
                raise ValueError("Agent 只接受名称唯一、范围受控且声明只读的插件")
            self.entries[tool.name] = (tool, config)

    def descriptors(self, installed, role="creative", has_project=True):
        """模型仅获得可调用名称、用途和参数 schema，不获得代码入口。"""
        return [
            {
                "name": tool.name,
                "version": tool.version,
                "description": tool.title,
                "arguments_schema": tool.input_model.model_json_schema(),
            }
            for tool, _ in self.entries.values()
            if set(tool.requires).issubset(installed)
            and role in getattr(tool, "roles", (tool.role,))
            and (has_project or tool.scope == "published_knowledge")
        ]

    def read(self, app, scope, name, raw_arguments):
        """实际读取处再次检查身份、资源范围与数据库只读限制。"""
        if name not in self.entries:
            raise DomainError("TOOL_NOT_ALLOWED", "该只读工具未开放", 403)
        tool, config = self.entries[name]
        if not set(tool.requires).issubset({module.id for module in app.state.modules}):
            raise DomainError("TOOL_NOT_ALLOWED", "查询模块未开放", 403)
        if (
            scope.role not in getattr(tool, "roles", (tool.role,))
            or tool.scope == "current_project"
            and not scope.project_id
        ):
            raise DomainError("TOOL_NOT_ALLOWED", "当前角色或项目范围不允许此查询", 403)
        arguments = tool.input_model.model_validate(raw_arguments)
        prepared = (
            tool.prepare(app, arguments, config["timeout_ms"])
            if callable(getattr(tool, "prepare", None))
            else None
        )
        with readonly_session(app, config["timeout_ms"]) as db:
            project = require_project(db, scope.project_id, scope.user_id) if scope.project_id else None
            user = db.get(User, scope.user_id)
            if (
                user is None
                or user.status != "active"
                or (project is not None and project.privacy_epoch != scope.privacy_epoch)
            ):
                raise DomainError("AUTHORIZATION_CHANGED", "项目授权已变化", 404)
            result = tool.output_model.model_validate(
                tool.read(app, db, scope, arguments, prepared)
                if callable(getattr(tool, "prepare", None))
                else tool.read(app, db, scope, arguments)
            ).model_dump(mode="json")
        if len(json.dumps(result, ensure_ascii=False)) > config["max_output_chars"]:
            raise DomainError("TOOL_OUTPUT_LIMIT", "查询结果过长，请指定具体任务", 422)
        return result


@contextmanager
def readonly_session(app, timeout_ms):
    """SQLite/PG 数据库层禁止工具写入，归还池连接前恢复本连接配置。"""
    with app.state.engine.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        driver = connection.connection.driver_connection
        deadline = monotonic() + timeout_ms / 1000
        old_busy = None
        try:
            if sqlite:
                old_busy = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql(f"PRAGMA busy_timeout={int(timeout_ms)}")
                driver.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            with Session(bind=connection, autoflush=False) as db:
                yield db
            if monotonic() > deadline:
                raise DomainError("TOOL_TIMEOUT", "查询超时，请稍后重试", 503)
        finally:
            connection.rollback()
            if sqlite:
                try:
                    driver.set_progress_handler(None, 0)
                    connection.exec_driver_sql("PRAGMA query_only=OFF")
                    connection.exec_driver_sql(f"PRAGMA busy_timeout={int(old_busy or 15000)}")
                    connection.rollback()
                except Exception:
                    connection.invalidate()


class CatalogResult(View):
    """面向客户的实时目录，不暴露图片原文、文件路径或供应商端点。"""

    styles: list[dict]
    max_count: int
    enabled_modes: list[str]


class CatalogTool:
    """查询当前风格与创作模式；精确报价仍由保存提案业务API计算。"""

    name, version, title = "get_catalog", "1", "查询当前创作目录"
    role, roles, scope, read_only = "creative", ("creative", "support"), "published_knowledge", True
    requires = ("catalog",)
    input_model, output_model = NoArguments, CatalogResult

    def read(self, app, db, scope, arguments):
        """只展示公开启用条目，有项目时限制到该项目类型。"""
        from app.modules.catalog.live import current_catalog
        from app.modules.projects.models import Project

        from .context import catalog_styles

        project = db.get(Project, scope.project_id) if scope.project_id else None
        catalog = current_catalog(app, db)
        return {
            "styles": catalog_styles(app, project.kind if project else None, catalog),
            "max_count": catalog["max_count"],
            "enabled_modes": catalog["enabled_modes"],
        }

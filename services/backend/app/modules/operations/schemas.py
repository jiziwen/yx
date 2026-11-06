"""管理端公开 DTO；只读脱敏事实，凭证、照片和供应商秘密均不进入契约。"""

from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.schemas import Input
from app.core.views import StyleView, View


class OverviewView(View):
    """权威统计；尚未采集的成本为 null。"""

    users: int
    projects: int
    jobs: dict[str, int]
    estimated_cost: None = None
    phase: str


class ModuleView(View):
    """启用模块及精确版本和依赖。"""

    id: str
    version: str
    requires: list[str]


class ProviderView(View):
    """只公开插件能力，不包含 options、密钥变量及上游 URL。"""

    id: str
    kind: str
    version: str
    capabilities: dict[str, Any]
    development_only: bool


class CatalogConfigView(View):
    """运营目录的版本化公开字段。"""

    version: str
    styles: list[StyleView]
    aspect_ratios: list[str]
    max_count: int


class InventoryView(View):
    """管理界面实际生效配置。"""

    catalog: CatalogConfigView
    features: dict[str, bool]
    modules: list[ModuleView]
    providers: list[ProviderView]


class AdminJobView(View):
    """任务事实摘要，不公开输入和私有对象路径。"""

    id: str
    project_id: str
    status: str
    provider_id: str
    error_code: str | None
    created_at: datetime


class AttemptView(View):
    """调用证据和费用；不含远端任务 ID、响应正文和文件 URL。"""

    request_key: str
    status: str
    error_code: str | None
    receipt_recorded: bool
    created_at: datetime
    finished_at: datetime | None
    next_poll_at: datetime | None
    latency_ms: int | None
    usage: dict[str, int] | None
    estimated_cost_micros: int | None
    estimated_currency: str | None
    actual_cost_micros: int | None
    currency: str | None


class JobDetailView(View):
    """核对能力来自服务端当前插件与冻结方案比较。"""

    job: AdminJobView
    revision: int
    attempt: AttemptView | None
    can_reconcile: bool
    recovery_reason: str


class JobActionInput(Input):
    """拒绝基于陈旧页面的运营动作，不接受手填成功或费用。"""

    expected_revision: int = Field(ge=1)


class AdminUserView(View):
    """用户身份摘要，不含手机号或登录摘要。"""

    id: str
    display_name: str
    role: str
    status: str
    created_at: datetime


class AuditView(View):
    """可审计动作与最小摘要。"""

    id: str
    actor_id: str
    action: str
    resource_id: str
    summary: dict[str, Any]
    created_at: datetime

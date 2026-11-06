"""独立客服会话与人工交接的版本、幂等及消息契约。"""

from datetime import datetime

from pydantic import Field

from app.core.schemas import Input
from app.core.views import View
from app.modules.agents.schemas import MessageView, RunView


class OpenSupport(Input):
    """可选当前用户项目；不绑定项目也能询问公开规则。"""

    project_id: str | None = None


class SupportSend(Input):
    """消息身份/角色由服务端决定，客户端只能提交正文。"""

    client_message_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1200)
    expected_revision: int = Field(ge=0)
    expected_privacy_epoch: int = Field(ge=0)


class HandoffInput(Input):
    """人工交接乐观版本锁，防止两个员工争抢/旧窗口交还。"""

    expected_revision: int = Field(ge=0)


class StaffReply(HandoffInput):
    """人工回复有独立幂等键，操作者由管理会话绑定。"""

    expected_privacy_epoch: int = Field(ge=0)

    client_message_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1200)


class SupportView(View):
    """公开客服状态；不返回创作草稿、照片、授权详情或内部提示词。"""

    id: str
    project_id: str | None
    revision: int
    privacy_epoch: int
    handoff_status: str
    assigned_staff_id: str | None
    messages: list[MessageView]
    runs: list[RunView]
    older_cursor: str | None
    enabled: bool
    model: str
    development_sample: bool


class SupportEntry(View):
    """员工工作台仅展示用户请求接管的会话元数据。"""

    id: str
    project_id: str | None
    revision: int
    handoff_status: str
    assigned_staff_id: str | None
    created_at: datetime


class ConversationEntry(View):
    """拥有者的会话入口列表，不包含消息正文或素材。"""

    id: str
    project_id: str | None
    entry_mode: str
    handoff_status: str
    revision: int
    created_at: datetime

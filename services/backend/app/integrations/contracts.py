"""供应商契约：业务仅依赖协议，不了解 SDK、密钥或上游 URL。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class ImageRequest:
    """冻结方案传给图片插件的最小输入。"""

    prompt: str
    aspect_ratio: str
    references: tuple[bytes, ...]
    request_key: str
    operation: str = "reference"
    input_roles: tuple[str, ...] = ()
    subject_bindings: tuple[dict, ...] = ()
    size: str | None = None


@dataclass(frozen=True)
class ImageResult:
    """适配器输出字节；落库和结算始终由媒体业务负责。"""

    content: bytes
    development_sample: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    actual_cost_micros: int | None = None
    currency: str | None = None


@dataclass(frozen=True)
class ImageSubmission:
    """上游接单凭据；必须持久化后才能查询，不包含照片或结果 URL。"""

    task_id: str


@dataclass(frozen=True)
class ImageLookup:
    """查询原任务的事实；unknown/未找到均不能作为退款或重发证据。"""

    status: Literal["pending", "succeeded", "failed", "cancelled", "unknown"]
    result: ImageResult | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class LLMResult:
    """可选的用量感知调用结果；金额缺少供应商证据时保持未知。"""

    data: dict
    usage: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class AsyncImageProvider(Protocol):
    """异步供应商只提交一次，之后仅凭已持久化的任务 ID 查询。"""

    def submit(self, request: ImageRequest) -> ImageSubmission:
        """提交一个交付项；提交超时必须进入未知状态。"""
        ...

    def lookup(self, task_id: str, request_key: str) -> ImageLookup:
        """查询已有外部任务；不得在本方法内创建新任务。"""
        ...


class ProviderFailure(Exception):
    """unknown 表示可能已被供应商接受，禁止自动重发和释放预占。"""

    def __init__(self, code: str, unknown: bool = False, retry_after_seconds: int | None = None):
        """初始化当前适配器或错误，不从浏览器接受凭证与权限。"""
        self.code, self.unknown = code, unknown
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


@runtime_checkable
class ImageProvider(Protocol):
    """一次调用只生成一个交付项；能力通过注册配置声明。"""

    def generate(self, request: ImageRequest) -> ImageResult:
        """只生成单个交付项，数据库结算由业务服务负责。"""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """返回结构化草稿，不能直接创建任务或扣除权益。"""

    def draft(self, messages: list[dict]) -> dict:
        """返回结构化草稿，不执行扣费或创建任务。"""
        ...


@runtime_checkable
class StreamingLLMProvider(Protocol):
    """可选增量能力；只回调 content 文本，最终仍返回完整结构化结果。"""

    def stream_complete(
        self, messages: list[dict], on_content: Callable[[str], None], timeout_seconds: float | None = None
    ) -> LLMResult:
        """网络失败禁止隐式改走完整请求，避免产生第二次付费调用。"""
        ...


@runtime_checkable
class Storage(Protocol):
    """私有对象存储；只有业务校验后才允许读对象。"""

    def put(self, key: str, content: bytes) -> None:
        """写入服务端签发的私有对象键。"""
        ...

    def get(self, key: str) -> bytes:
        """读取已经由业务服务授权的对象。"""
        ...

    def delete(self, key: str) -> None:
        """幂等删除指定私有对象。"""
        ...

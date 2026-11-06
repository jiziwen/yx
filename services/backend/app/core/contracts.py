"""M0 公共 HTTP 契约；所有错误包含可关联的 request_id，不回显输入或凭证。"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """可供用户操作的错误，details 只包含非敏感字段名与约束分类。"""

    code: str = Field(description="稳定的机器可读错误码")
    message: str = Field(description="用户可见说明，不包含上游正文")
    request_id: str = Field(description="与 X-Request-ID 一致的请求关联 ID")
    details: dict[str, Any] | list[dict[str, Any]] | None = Field(
        default=None, description="可选非敏感上下文"
    )


class ErrorEnvelope(BaseModel):
    """统一错误信封。"""

    error: ErrorBody


class OkView(BaseModel):
    """明确成功的无载荷动作。"""

    ok: Literal[True] = True


class CodeView(BaseModel):
    """开发验证码响应；生产禁止启用该入口。"""

    development_only: Literal[True] = True
    debug_code: str = Field(description="仅在开发环境返回的验证码")
    expires_in: int = Field(description="有效期，单位秒")


class HealthView(BaseModel):
    """进程健康，不替代数据库兼容性检查。"""

    status: Literal["ok"] = "ok"
    version: str


class ReadyView(BaseModel):
    """当前数据库必须与已发布代码需要的迁移头一致。"""

    status: Literal["ready"] = "ready"
    migration: str


ERROR_RESPONSES = {
    status: {"model": ErrorEnvelope, "description": description}
    for status, description in {
        400: "业务参数错误",
        401: "未登录或会话已失效",
        403: "权限或请求来源不允许",
        404: "资源不存在或不可见",
        409: "版本、并发或幂等冲突",
        413: "上传超出限制",
        422: "字段校验失败",
        429: "请求过于频繁",
        500: "内部错误",
        503: "依赖暂不可用",
    }.items()
}

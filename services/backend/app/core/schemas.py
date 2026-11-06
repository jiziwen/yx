"""公开请求基类：白名单字段与稳定序列化规则。"""

from pydantic import BaseModel, ConfigDict


class Input(BaseModel):
    """未知字段拒绝，防止传入 role、price、accepted 等越权属性。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

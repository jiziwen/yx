"""供应商凭证读取只在服务端；环境变量优先，支持本地受忽略的 .env。"""

import os
import re
from pathlib import Path

from dotenv import dotenv_values


def provider_secret(settings, name: str) -> str:
    """不把凭证内容或 dotenv 解析结果返回到公开配置和日志。"""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,100}", name):
        raise ValueError("供应商密钥变量名无效")
    if name in os.environ:
        return os.environ[name]
    source = settings.model_config.get("env_file")
    return (dotenv_values(Path(source)).get(name) or "") if source and Path(source).is_file() else ""

"""离线导出默认完整接口契约；不读部署凭证、不创建数据库、不初始化供应商。"""

import json

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    """使用代码内置默认清单；部署关闭模块由能力接口表达，不改变客户端类型来源。"""
    settings = Settings.model_construct()
    application = create_app(settings, contract_only=True)
    print(json.dumps(application.openapi(), ensure_ascii=False))


if __name__ == "__main__":
    main()

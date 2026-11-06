"""代码与数据库的迁移兼容性检查；不把仅能连接数据库当作可提供服务。"""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.core.config import ROOT


def expected_migrations() -> set[str]:
    """从发布镜像中的迁移文件读取头版本，避免手动维护第二份版本常量。"""
    configuration = Config()
    configuration.set_main_option("script_location", str(ROOT / "migrations"))
    return set(ScriptDirectory.from_config(configuration).get_heads())


def check_migrations(engine: Engine) -> str:
    """数据库必须与代码迁移头一致；调用者负责包装脱敏错误。"""
    with engine.connect() as connection:
        actual = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    if actual != expected_migrations() or len(actual) != 1:
        raise RuntimeError("database schema does not match this release")
    return next(iter(actual))

"""受控管理命令：交互或 stdin 开通管理员，密码不得放到命令行参数中。"""

import argparse
import getpass
import sys

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import make_engine
from app.core.errors import DomainError
from app.modules.identity.credentials import provision_admin


def main(argv: list[str] | None = None) -> int:
    """先迁移再开通；重复账号不更新原凭证，不产生外部消息。"""
    parser = argparse.ArgumentParser(description="映序受控管理命令")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="开通新的管理员，不覆盖原凭证")
    create.add_argument(
        "--role", choices=["admin", "staff"], default="admin", help="客服员工不能发布知识、修改模型或管理权益"
    )
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", default="映序管理员")
    create.add_argument("--password-stdin", action="store_true", help="从 stdin 单行读取，供受控部署使用")
    options = parser.parse_args(argv)
    if options.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("管理密码（至少 12 位）：")
        if password != getpass.getpass("再次输入："):
            print("两次密码不一致", file=sys.stderr)
            return 2
    engine = make_engine(Settings().database_url)
    try:
        with Session(engine) as db:
            user = provision_admin(db, options.username, password, options.display_name, role=options.role)
            db.commit()
            print(f"管理员已开通，user_id={user.id}")
        return 0
    except DomainError as exc:
        print(exc.message, file=sys.stderr)
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

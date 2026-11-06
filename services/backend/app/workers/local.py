"""开发用独立轮询 Worker；生产通过 Celery 与独立维护队列运行。"""

import logging
import time

from app.main import create_app

from .runtime import tick


def main():
    """循环消费数据库 outbox；故障只记录类别，不输出敏感正文。"""
    app = create_app()
    if app.state.settings.app_env == "production":
        raise RuntimeError("生产请使用 Celery 和 scheduler")
    while True:
        try:
            tick(app)
        except Exception as exc:
            logging.error("worker_tick_failed kind=%s", type(exc).__name__)
        time.sleep(1)


if __name__ == "__main__":
    main()

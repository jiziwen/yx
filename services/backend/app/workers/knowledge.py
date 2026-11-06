"""独立本地知识Worker，解析/embedding不占图片或Agent执行容量。"""

import logging
import time

from app.main import create_app
from app.modules.knowledge.worker import maintain, pending, process


def main():
    """生产使用knowledge队列，本地显式开发进程有界扫描持久任务。"""
    app = create_app()
    if app.state.settings.app_env == "production":
        raise RuntimeError("生产请使用knowledge Celery队列")
    while True:
        try:
            maintain(app)
            for job_id in pending(app):
                process(app, job_id)
        except Exception as exc:
            logging.error("knowledge_tick_failed kind=%s", type(exc).__name__)
        time.sleep(1)


if __name__ == "__main__":
    main()

"""本地 Agent 独立进程，LLM 等待不会阻塞图片 Worker。"""

import logging
import time

from app.main import create_app

from .agent_runtime import maintain_runs, pending_runs, process_run


def main():
    """生产使用 agents 队列，开发以数据库扫描恢复未处理的消息。"""
    app = create_app()
    if app.state.settings.app_env == "production":
        raise RuntimeError("生产请使用 agents Celery 队列")
    while True:
        try:
            maintain_runs(app)
            for run_id in pending_runs(app):
                process_run(app, run_id)
        except Exception as exc:
            logging.error("agent_tick_failed kind=%s", type(exc).__name__)
        time.sleep(0.5)


if __name__ == "__main__":
    main()

"""Celery 生产执行入口；重复队列投递依靠数据库状态机去重。"""

from contextlib import contextmanager

from celery import Celery

from app.core.config import Settings
from app.main import create_app
from app.modules.identity.auth_state import RedisAuthState

from .runtime import maintenance, process_job, reconcile_job

settings = Settings()
celery_app = Celery("yingxu", broker=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_routes={
        "yingxu.media": {"queue": "media"},
        "yingxu.reconcile": {"queue": "media"},
        "yingxu.maintenance": {"queue": "maintenance"},
        "yingxu.agent": {"queue": "agents"},
        "yingxu.knowledge": {"queue": "knowledge"},
    },
)


@contextmanager
def worker_app():
    """任务结束释放进程内创建的连接池，避免长时间运行积累连接。"""
    app = create_app()
    try:
        yield app
    finally:
        if isinstance(app.state.auth_state, RedisAuthState):
            app.state.auth_state.close()
        app.state.engine.dispose()


@celery_app.task(name="yingxu.media")
def media(job_id: str):
    """短消息只带 Job ID，照片与凭证不进入 Redis。"""
    with worker_app() as app:
        process_job(app, job_id)


@celery_app.task(name="yingxu.reconcile")
def reconcile(job_id: str):
    """消息仅携带本地 ID；恢复不创建第二次供应商提交。"""
    with worker_app() as app:
        reconcile_job(app, job_id)


@celery_app.task(name="yingxu.maintenance")
def maintain():
    """隐私清理不与媒体长任务争抢同一队列。"""
    with worker_app() as app:
        maintenance(app)
        from .agent_runtime import maintain_runs

        maintain_runs(app)
        from app.modules.knowledge.worker import maintain as maintain_knowledge

        maintain_knowledge(app)


@celery_app.task(name="yingxu.agent")
def agent(run_id: str):
    """Agent 独立队列只携带 Run ID；重复投递没有重复调用。"""
    from .agent_runtime import process_run

    with worker_app() as app:
        process_run(app, run_id)


@celery_app.task(name="yingxu.knowledge")
def knowledge(job_id: str):
    """知识队列只带系统索引任务ID，不接收用户照片。"""
    from app.modules.knowledge.worker import process

    with worker_app() as app:
        process(app, job_id)

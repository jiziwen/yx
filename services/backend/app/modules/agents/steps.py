"""公开运行步骤持久化；只记录来源摘要和数值用量，不保存隐藏思考。"""

from sqlalchemy import func, select

from app.core.db import now

from .models import AgentStep


def start_step(db, run, kind, name, manifest=None):
    """调用方持有Run锁，尝试计数和步骤在外部调用前同事务提交。"""
    sequence = (db.scalar(select(func.max(AgentStep.seq)).where(AgentStep.run_id == run.id)) or 0) + 1
    step = AgentStep(
        run_id=run.id, seq=sequence, kind=kind, name=name, status="running", manifest_json=manifest or {}
    )
    db.add(step)
    db.flush()
    return step


def end_step(db, step_id, *, usage=None, error=None):
    """迟到调用只补充尝试证据，不复活被取消/失败的运行。"""
    step = db.get(AgentStep, step_id)
    if step and usage is not None:
        step.usage_json = usage
    if step and step.status == "running":
        step.status = "failed" if error else "succeeded"
        step.error_code = error
        step.usage_json = usage
        step.finished_at = now()

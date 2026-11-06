"""模型增量到短事务的桥接；临时回复按 Run/尝试归属，网络期间不持有写锁。"""

from time import monotonic

from app.core.db import now
from app.integrations.contracts import ProviderFailure
from app.modules.agents.service import enabled
from app.modules.agents.streaming import reply_prefix
from app.modules.media_jobs.governance import aware

from .runtime import begin_write


class ReplyPublisher:
    """有界拼接、只提取可见 reply、节流持久化；不写 Message/Plan/Job。"""

    def __init__(self, app, run_id, token, attempt_no, flush_ms):
        """一次真实模型调用一个实例，重试不复用文字或序号。"""
        self.app, self.run_id, self.token, self.attempt_no = app, run_id, token, attempt_no
        self.raw, self.latest, self.saved, self.seq = "", "", "", 0
        self.interval, self.flushed = flush_ms / 1000, 0.0

    def content(self, chunk):
        """收到供应商 content 后调用，绝不将完整 JSON 当作回复显示。"""
        self.raw += chunk
        if len(self.raw) > 65536:
            raise ProviderFailure("PROVIDER_INVALID_OUTPUT")
        text = reply_prefix(self.raw)
        if text is not None:
            self.latest = text
        self.flush()

    def flush(self, force=False):
        """只保存变化的整段前缀；校验执行权、截止时间及当前项目输入。"""
        if self.latest == self.saved or not self.latest:
            return
        if not force and monotonic() - self.flushed < self.interval:
            return
        from .agent_runtime import lock_run, valid_inputs

        with self.app.state.sessions() as db:
            begin_write(db)
            project, _, run = lock_run(db, self.run_id)
            if (
                run is None
                or run.status != "running"
                or run.lease_token != self.token
                or run.calls != self.attempt_no
            ):
                raise ProviderFailure("AGENT_CANCELLED")
            if aware(run.deadline_at) <= now():
                raise ProviderFailure("AGENT_TIMEOUT")
            if not enabled(self.app):
                raise ProviderFailure("CHAT_DISABLED")
            valid_inputs(db, project, run, self.app)
            self.seq += 1
            run.stream_json = {
                "run_id": run.id,
                "attempt_no": self.attempt_no,
                "seq": self.seq,
                "text": self.latest,
                "privacy_epoch": run.privacy_epoch,
            }
            run.stage = "responding"
            db.commit()
        self.saved, self.flushed = self.latest, monotonic()

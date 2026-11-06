<!-- media_jobs 职责与调用边界。 -->
# media_jobs

负责任务状态、取消、执行意图和结算协调。公开入口为 `manifest.py` 和 `api.py`，复杂用例在 `service.py`。

数据归属：Job/Outbox/ProviderAttempt/RuntimeGate；未知结果不自动重发。governance.py 在共享数据库短事务中校验入口容量和账号并发/速率/熔断，未知远端任务仍占槽。同步返回与异步查询共用 Worker 的交付/权益事务；Celery 和本地调度均按用户轮转并查询已有凭据。

稳定请求键、接单凭据、数值用量、估算/确认金额与币种由尝试表保存；原始照片、上游正文、结果 URL 和密钥不落该表。依赖见 manifest；数据库变更统一由 Alembic 执行，关闭模块保留历史。

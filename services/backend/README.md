<!-- 模块化后端的实际入口、运行模式和验证限制。 -->
# 映序后端

模块化 FastAPI 单体，持久化状态归 SQLAlchemy 业务表。Alembic 管理迁移；启动不执行 create_all。Python 3.12 与依赖由 uv/uv.lock 锁定。

```sh
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8100
uv run python -m app.workers.local
uv run python -m app.workers.agent  # 独立终端处理工作室 LLM 对话
uv run pytest
```

API 与 Worker 在不同终端。根目录 `pnpm dev` 可同时启动所有进程。`.env.example` 展示环境配置，`resources/application.yaml` 声明模块与网关，`resources/catalog.yaml` 声明风格。默认本地 SQLite/私有目录/开发验证码，生产防护见 Settings。

- `app/modules`：identity、projects、assets、executions、commerce、media_jobs、catalog、operations、conversations、agents 及清单。
- `app/integrations`：同步/异步供应商协议、网关、开发插件、302.AI 统一异步图片插件与可配置 HTTP 候选适配器。
- `app/workers/runtime.py`：领取、外部提交、授权复核、交付、结算及清理恢复。
- `app/workers/celery_app.py`：media/agents/maintenance 三个队列；`scheduler.py` 只扫描投递。
- `tests`：业务原子性、权限、供应商故障、撤销与插件启动约束。

M0 新增：`app.cli create-admin` 受控开通管理账户，密码只保存随机盐摘要；独立管理 TTL；内存/Redis 认证状态；离线 `python -m app.export_openapi`；精确迁移头 readiness 与通用错误信封。`admin_credentials` 是 M0 的附加认证表，不属于原设计 25 张业务核心表，升级迁移不修改旧用户和项目。

`uv run ruff check .` / `uv run ruff format --check .` 是质量门禁；`evals` 保存供应商样例定义与评分标准。`pnpm check:m0` 将两端、后端、契约、PostgreSQL、Redis 与浏览器检查整合为一个可重复命令。

M1 新增 `da3987b1b6c4` 迁移、异步接单凭据/查询恢复、共享数据库账号并发/速率/熔断、入口队列容量与用户轮转，以及管理端调用详情/审计核对。Celery 的 media 队列同时处理提交与 reconcile 任务，maintenance 独立清理。默认关闭的 ai302-image 使用 AI302_API_KEY 与每操作可配置模型；见 [M1 接入说明](../../docs/M1供应商与任务恢复.md)。

V1.5 新增 a06b4bffb961 模型发布表、AI302GPTImage 原生异步接口和后台 /models。当前本地数据库已发布 gpt-image-2 / low 和 claude-sonnet-5-5，真实文生图与短 JSON 通过。密钥仅由 .env/环境变量读取；runtime live 网关保留不可变历史并跨进程读取发布指针。模型/质量/能力可在线发布，代码入口和上游地址仍固定在服务端。操作与验收见 [后台模型配置](../../docs/后台模型配置.md)。

未知外部结果不释放预占、不自动重发。有凭据时可查询原任务，无凭据需供应商记录人工核对。`python -m evals.preflight` 只检查配置、凭证存在和授权素材，不发付费请求。真实效果/费用、回调验签、账单核对导入、S3、短信与管理二次验证尚未完成整体部署验收。

现有隐私清理覆盖人物撤销、参考图和连续编辑的多代照片血缘；完整项目/账户删除、赠品、cleanup epoch/租约和高容量分批清理按后续文档实现。当前无 API 接受任意项目/账户永久删除。

V1.6 新增 conversations/agents、b9ff639728f2 迁移与独立 Agent Worker；后台已发布 LLM 用于需求理解、追问和受白名单校验的草稿，不调用图片/权益接口。配置入口为 resources/application.yaml 的 agent，运行/取消/上下文边界见 [M2 创作 Agent](../../docs/M2创作Agent.md)。显式真实两轮联调：`uv run python -m evals.agent_smoke --live`，不在默认测试或 CI 中运行。

V1.7 新增 project_memory 与 ffba47dfea56：仅用户明确确认写入长期要求，按隐私代次与版本保护。agent.tools 配置受控只读插件，Run 记录工具预算/证据并复核记忆版本；SQLite query_only 和 PostgreSQL 只读事务禁止查询误写。真实联调可显式执行 `uv run python -m evals.agent_smoke --live --memory-tools`；不运行图片。详情见 [项目记忆与只读工具](../../docs/M2项目记忆与只读工具.md)。

V1.8：conversations/events.py 提供周期鉴权、不持有长事务的数据库 SSE 失效通知，conversation_stream 独立配置；不绑定特定 LLM，不增加迁移。见 [实时对话与提案对比](../../docs/M2实时对话与提案对比.md)。

V1.9：可选 StreamingLLMProvider 与 ReplyPublisher 将原生 content 转为有界 reply 前缀；新增 a38f94cce1d2 的 stream_json，终态/取消清空，正式消息仍原子提交。显式真实验收 `uv run python -m evals.agent_smoke --live --stream`，不调用图片。见 [逐字流式回复](../../docs/M2逐字流式回复.md)。

V1.10：新增配置化创作需求卡（用户明确确认才保存）、消息 cursor 分页与阅读位置保留、带原话来源的只读历史查询。替换/删除要求后旧记录不再供 Agent 检索；图片仍须用户确认。配置与验收见 [创作需求卡与历史管理](../../docs/M2创作需求卡与历史管理.md)。

V1.11：M2全量功能已补齐：知识导入/索引/发布/指南、混合RAG与授权引用、独立客服与人工接管、员工权限、公开Run Step及精确Release/固定评测。图片仍须用户确认；主题/网关/工具可配置、可插拔。统一工程检查 `pnpm check:m2`，真实重复抽样与人工质量批准单独记录。入口和当前验收见[完整M2说明](../../docs/M2完整交付与验收.md)。

语言/视觉Agent的网络等待由 `agent.request_timeout_seconds` 统一控制，当前为300秒；`agent.deadline_seconds` 为330秒，包含上下文、工具和最终校验时间。网关对运行实例应用该预算，不改写历史模型发布定义；新Run冻结预算和调用租约，历史60秒配置不会截断新请求。图片适配器的网络超时独立配置。回归：`tests/test_agent_timeouts.py`。

<!-- 自动化脚本职责与作用范围。 -->
# 工程脚本

`dev.mjs` 同步后端依赖并迁移，再启动 API、独立媒体/Agent Worker 和两个前端。只停止自己启动的子进程组；不会释放其他项目占用的端口。迁移前应备份需要保留的数据。

`generate-api.mjs` 在临时目录导出 OpenAPI 并生成 `packages/api-client/src/generated.ts`，`--check` 只比较漂移，不修改源码。

`test-postgres.mjs` 使用临时 Docker 容器验证 PostgreSQL 迁移和 HTTP 闭环，结束后删除自己创建的容器。不连接或修改用户已有数据库。

`quality.mjs` 检查 TypeScript/配置格式及 Python 语法、导入和必要说明；TypeScript 的未使用符号由严格编译检查。

`check-m0.mjs` 依次执行 10 个工程门禁，失败即停止并将状态写到 `.data/m0/last-run.json`。需要 Docker、uv、pnpm 及已安装的 Chromium；不会以跳过依赖的方式报告全部通过。

`test-redis.mjs` 创建临时 Redis 容器验证跨 API 验证码、原子消费、限流和过期，结束清理。Playwright 使用独立端口与每轮临时数据库，发送 SIGTERM 让开发脚本回收自己创建的进程组。验证码、照片和密码不写入验收报告。

V1.6：同一 M1 工程验收入口纳入创作 Agent 合约、草稿保护和 PostgreSQL 并发场景；真实两轮 LLM 验收只通过后端 `python -m evals.agent_smoke --live` 显式运行，不纳入 CI，不生成图片。

M2入口 `pnpm check:m2` 在M1工程门禁基础上加入固定Agent/RAG评测；报告.data/m2/last-run.json，CI使用同一入口。PostgreSQL测试使用带pgvector的临时独立容器；脚本只回收自己创建的容器和夹具。生产质量批准不是脚本自动结论。

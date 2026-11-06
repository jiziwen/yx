<!-- 部署配置的使用范围、执行顺序和当前验证限制。 -->
# 部署与运行

当前优先验证本地开发闭环。`compose.dev.yml` 仅提供 PostgreSQL/pgvector 与 Redis，不要求它们才能运行默认 SQLite 联调。

```sh
docker compose -f deploy/compose.dev.yml up -d
```

需要 PostgreSQL 时把后端 `DATABASE_URL` 配置为对应连接，先迁移，再启动 API、Worker。开发示例账号只限回环地址。不要对需要保留的卷执行 `down -v`。

`docker/backend.Dockerfile` 为 API、Celery 媒体/维护 Worker 和 scheduler 复用镜像。`docker/frontend.Dockerfile` 用 `APP_NAME=web` 或 `admin` 独立生成静态包。Nginx 配置假定内部后端名 `api`、端口 8100；实际环境应配置 TLS、受控 Origin 和独立域名。

容器镜像与集群整体尚未完成生产验收。没有提供伪装可上线的 compose.prod：真实短信、S3、供应商账号级共享限额、管理二次验证、供应商核对、监控与备份仍未完成。生产配置会拒绝开发登录、开发供应商、SQLite 和默认会话密钥。

发布遵循 `docs/runbooks`。迁移先于应用升级；现有方案绑定网关配置摘要，不能通过切换模型悄悄改变用户已确认的规格。回滚前应确认旧版本可读取现有数据与任务。

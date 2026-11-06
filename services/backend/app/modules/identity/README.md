<!-- identity 职责与调用边界。 -->
# identity

负责登录、独立会话及角色校验。公开入口为 `manifest.py` 和 `api.py`；`credentials.py` 管理受控开通及随机盐密码摘要，`auth_state.py` 提供内存/Redis 认证状态协议与实现。

数据归属：User、AdminCredential；不负责模型意图和扣费。依赖见 manifest；模块通过业务服务调用协作，不能直接越过授权和事务边界。数据库变更统一由 Alembic 执行；关闭模块保留其历史表。

生产使用 `ADMIN_AUTH_MODE=database` 与 `AUTH_STATE_BACKEND=redis`，管理员由 `uv run python -m app.cli create-admin --username ops` 开通。密码通过交互或 `--password-stdin` 提供；已有账号不会覆盖。开发模式首次正确登录可初始化本地凭证，初始化后修改 `ADMIN_PASSWORD` 不会重置密码。

用户和管理员使用独立 Cookie、签名盐和有效期。验证码由 Redis 原子校验/消费；限流状态跨进程共享，Redis 不可用时拒绝认证。真实短信与管理二次验证在供应商接入阶段补齐。

<!-- commerce 职责与调用边界。 -->
# commerce

负责项目权益和只追加流水。公开入口为 `manifest.py` 和 `api.py`，复杂用例在 `service.py`。

数据归属：Account/EntitlementEvent；本阶段无支付、钱包和退款。依赖见 manifest；模块通过业务服务调用协作，不能直接越过授权和事务边界。数据库变更统一由 Alembic 执行；关闭模块保留其历史表。

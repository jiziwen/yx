<!-- executions 职责与调用边界。 -->
# executions

负责固定方案版本、冻结输入、确认与原子建任务。公开入口为 `manifest.py` 和 `api.py`，复杂用例在 `service.py`。

数据归属：Plan/Approval/Idempotency；前端和模型不能直接结算。依赖见 manifest；模块通过业务服务调用协作，不能直接越过授权和事务边界。数据库变更统一由 Alembic 执行；关闭模块保留其历史表。

V1.3：`creation.py` 将 template/portrait/edit/text 编译为逐交付项输入；校验用途、选用、授权、镜头位置、总数和供应商能力。schema 2 沿用 JSON 列，明确冻结 inputs/items、镜头摘要和供应商。旧 schema 1 继续可读，旧请求动作键保持原语义。保存不扣次数，确认原子预占并创建 Job；不允许浏览器提供消耗、内部 items 或供应商凭证。

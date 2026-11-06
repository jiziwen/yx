<!-- 共享客户端包的契约来源、边界与验证。 -->
# @yingxu/api-client

两个前端共同使用的 fetch 包装、错误类型和业务 DTO。`src/generated.ts` 由 FastAPI OpenAPI 生成，禁止手改；运行根目录 `pnpm api:generate` 更新，`pnpm api:check` 检查漂移。

请求使用同源 `/api/v1` 与 HttpOnly Cookie。调用方为一次业务动作产生固定幂等键；自动重试不得换键。图片使用私有代理地址，不能将照片数据或会话写入 localStorage。

`pnpm --filter @yingxu/api-client typecheck` 校验源码。此包发布源码，由各前端独立构建，无单独服务或全局状态。

M0 新增 `api.GET/POST` 类型化入口与 `expectData`，路径、方法、路径参数和 DTO 来自生成契约；两端身份/目录调用已切换。错误中间件兼容正常信封、null、HTML 与网络故障并保留 request_id。`pnpm test:client` 验证序列化、Cookie 策略与错误分流；编译期断言检查错误方法/路径/缺少参数/非法 DTO 字段。

历史业务功能仍可使用 `request<T>`，它不具备路径和请求体的编译期校验。后续 M1 改动应优先迁移到 `api`，不能把手工泛型断言当成契约校验。

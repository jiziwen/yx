<!-- catalog 职责与调用边界。 -->
# catalog

负责版本化风格目录与前端能力清单。公开入口为 `manifest.py` 和 `api.py`，复杂用例在 `service.py`。

数据归属：resources/catalog.yaml；不是在线任意配置平台。依赖见 manifest；模块通过业务服务调用协作，不能直接越过授权和事务边界。数据库变更统一由 Alembic 执行；关闭模块保留其历史表。

V1.3：`configuration.py` 校验套系、镜头和素材路径，启动时规范化图片并计算摘要。公开 DTO 返回 shots、creation_modes 与 upload_limits，不返回路径、二进制或密钥。镜头内容通过公开 inspiration API 读取，用户素材继续私有隔离。mode→operation 对应 template/edit、portrait/reference、edit/edit、text/text；可选操作路由取自网关。生产过滤 development_only 镜头。

动态目录由`models.py`及`live.py`提供：YAML为初始目录，后台保存完整数据库发布快照，API/Agent/Worker按数据库指针读取，不需重启。上传通过可插拔Storage保存不可变对象，公开/管理预览与用途分开；冻结输入同时校验图片和用途摘要。管理入口属于operations的`theme_materials.py`，仅admin可上传和保存；保存即生效，保留历史和并发防重。

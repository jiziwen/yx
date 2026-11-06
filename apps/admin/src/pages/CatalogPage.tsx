/** 管理端独立功能文件；后端 API 始终校验管理员角色。 */
import { useQuery } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { Blocks } from 'lucide-react';
import { State, Title } from '../shared/ui';
/** 部署配置实际生效清单，配置变更需验证依赖并重新发布。 */
export default function Catalog() {
  const data = useQuery({
    queryKey: ['admin-catalog'],
    queryFn: () => api.GET('/api/v1/admin/catalog').then(expectData),
  });
  return (
    <div className="page">
      <Title
        title="模块与配置"
        description="可插拔业务模块、模型网关与功能开关的当前生效版本。"
        onRefresh={() => data.refetch()}
      />
      {data.isLoading ? (
        <State>加载中…</State>
      ) : data.error ? (
        <State error={data.error} retry={() => data.refetch()} />
      ) : (
        data.data && (
          <>
            <section className="panel">
              <div className="panel-title">
                <h2>业务模块</h2>
                <span>{data.data.modules.length} 个已启用</span>
              </div>
              <div className="module-grid">
                {data.data.modules.map((module) => (
                  <article className="module-card" key={module.id}>
                    <Blocks size={19} />
                    <h3>
                      {module.id}
                      <small>v{module.version}</small>
                    </h3>
                    <p>依赖：{module.requires.join(' · ') || '无'}</p>
                    <span className="badge active">已启用</span>
                  </article>
                ))}
              </div>
            </section>
            <section className="panel">
              <div className="panel-title">
                <h2>模型与基础设施网关</h2>
                <span>能力契约校验</span>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>插件 ID</th>
                      <th>类型</th>
                      <th>版本</th>
                      <th>环境</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.data.providers.map((provider) => (
                      <tr key={provider.id}>
                        <td>{provider.id}</td>
                        <td>{provider.kind}</td>
                        <td>{provider.version}</td>
                        <td>
                          <span
                            className={'badge ' + (provider.development_only ? 'queued' : 'active')}
                          >
                            {provider.development_only ? '仅开发' : '可接入真实服务'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="panel">
              <div className="panel-title">
                <h2>功能开关</h2>
                <span>未接入功能不提供操作</span>
              </div>
              <div className="flags">
                {Object.entries(data.data.features).map(([name, value]) => (
                  <div key={name}>
                    <code>{name}</code>
                    <span className={'badge ' + (value ? 'active' : 'cancelled')}>
                      {value ? '已启用' : '已关闭'}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </>
        )
      )}
    </div>
  );
}

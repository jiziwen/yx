/** 管理端独立功能文件；后端 API 始终校验管理员角色。 */
import { useQuery } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { ShieldCheck } from 'lucide-react';
import { State, Title } from '../shared/ui';
import { labels } from '../shared/status';
/** 运营概览只显示已采集事实，没有成本数据时明确标记。 */
export default function Overview() {
  const data = useQuery({
    queryKey: ['admin-overview'],
    queryFn: () => api.GET('/api/v1/admin/overview').then(expectData),
  });
  return (
    <div className="page">
      <Title
        title="运营概览"
        description="创作、交付与任务运行的当前快照。"
        onRefresh={() => data.refetch()}
      />
      {data.isLoading ? (
        <State>加载中…</State>
      ) : data.error ? (
        <State error={data.error} retry={() => data.refetch()} />
      ) : (
        data.data && (
          <>
            <div className="metrics">
              {[
                ['用户数', data.data.users, '普通创作者'],
                ['项目数', data.data.projects, '独立私人影像空间'],
                ['已完成', data.data.jobs.succeeded ?? 0, '成功交付的照片任务'],
                [
                  '待核对',
                  data.data.jobs.reconciliation_required ?? 0,
                  '权益保留预占，需核对外部事实',
                ],
              ].map(([label, value, description]) => (
                <article key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                  <small>{description}</small>
                </article>
              ))}
            </div>
            <section className="panel">
              <div className="panel-title">
                <h2>任务分布</h2>
                <span>数据库权威状态</span>
              </div>
              {Object.keys(data.data.jobs).length ? (
                <div className="distribution">
                  {Object.entries(data.data.jobs).map(([status, count]) => (
                    <div key={status}>
                      <span className={'badge ' + status}>{labels[status] ?? status}</span>
                      <div className="bar">
                        <i
                          style={{
                            width:
                              (count / Math.max(1, ...Object.values(data.data!.jobs))) * 100 + '%',
                          }}
                        />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              ) : (
                <State>还没有生成任务。用户确认方案后，任务会出现在这里。</State>
              )}
            </section>
            <section className="panel note-panel">
              <ShieldCheck size={20} />
              <div>
                <h3>当前开发阶段：M2</h3>
                <p>
                  创作
                  Agent、知识发布与检索、人工客服及运行记录已接入。生成仍需用户确认；模型质量和真实账单分别验收，赠品与售后继续后续阶段。
                </p>
              </div>
            </section>
          </>
        )
      )}
    </div>
  );
}

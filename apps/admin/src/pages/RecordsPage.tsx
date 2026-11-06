/** 管理端独立功能文件；后端 API 始终校验管理员角色。 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { request } from '@yingxu/api-client';
import { State, Title } from '../shared/ui';
import type { Row } from '../app/types';
import JobDetail from './JobDetail';
import { labels } from '../shared/status';
/** 格式化有界元信息；不把任意 HTML 作为运营内容渲染。 */
function cell(value: unknown) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
/** 通用只读运营表，默认不提供用户照片或未实现的写操作。 */
export default function Records({ kind }: { kind: 'jobs' | 'users' | 'audit' }) {
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const data = useQuery({
    queryKey: ['admin', kind],
    queryFn: () => request<Row[]>('/admin/' + kind),
  });
  const titles = {
    jobs: ['生成任务', '查看调用证据与费用，查询原供应商任务。未知外部结果保留预占。'],
    users: ['用户与项目', '脱敏账户列表，不展示手机号和用户参考照片。'],
    audit: ['操作审计', '关键授权与业务动作的持久化记录。'],
  };
  const columns: Record<string, string> =
    kind === 'jobs'
      ? {
          id: '任务 ID',
          project_id: '项目 ID',
          status: '状态',
          provider_id: '供应商',
          error_code: '错误分类',
        }
      : kind === 'users'
        ? { id: '用户 ID', display_name: '显示名称', role: '角色', status: '状态' }
        : {
            id: '记录 ID',
            actor_id: '操作人',
            action: '动作',
            resource_id: '资源 ID',
            summary: '摘要',
          };
  const rows = (data.data ?? []).filter(
    (row) =>
      !filter ||
      Object.values(row).some((value) => cell(value).toLowerCase().includes(filter.toLowerCase())),
  );
  return (
    <div className="page">
      <Title
        title={titles[kind][0]}
        description={titles[kind][1]}
        onRefresh={() => data.refetch()}
      />
      {kind === 'users' && (
        <p>
          <Link className="outline" to="/entitlements">
            增加项目次数 / 查看发放记录
          </Link>
        </p>
      )}
      <section className="panel">
        <div className="table-toolbar">
          <span>最近 100 条记录</span>
          <input
            aria-label="筛选记录"
            placeholder="筛选 ID、状态或名称…"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
        {data.isLoading ? (
          <State>加载中…</State>
        ) : data.error ? (
          <State error={data.error} retry={() => data.refetch()} />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {Object.values(columns).map((name) => (
                    <th key={name}>{name}</th>
                  ))}
                  {kind === 'jobs' && <th>调用记录</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={cell(row.id)}>
                    {Object.keys(columns).map((key) => (
                      <td title={cell(row[key])} key={key}>
                        {key === 'status' || key === 'role' ? (
                          <span className={'badge ' + cell(row[key])}>
                            {labels[cell(row[key])] ?? cell(row[key])}
                          </span>
                        ) : (
                          cell(row[key])
                        )}
                      </td>
                    ))}
                    {kind === 'jobs' && (
                      <td>
                        <button className="record-action" onClick={() => setSelected(cell(row.id))}>
                          查看详情
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <State>暂无符合条件的记录。</State>}
          </div>
        )}
      </section>
      {kind === 'jobs' && selected && (
        <JobDetail key={selected} id={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

/** 运营核对原任务，只展示脱敏调用证据，不提供重新付费提交。 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { State } from '../shared/ui';
import { labels } from '../shared/status';

const reasons: Record<string, string> = {
  terminal: '任务已经结算。重复消息不会重复交付或扣除权益。',
  not_submitted: '尚未提交供应商，可以取消排队。',
  missing_receipt: '未获得上游接单凭据。请通过供应商账单与请求记录人工核对，系统保留预占。',
  config_changed: '供应商配置与冻结方案不一致。恢复原配置后才能查询。',
  unsupported: '当前适配器没有查询能力，需人工核对供应商记录。',
  querying: '已有查询正在进行，请稍后刷新。',
  ready: '只查询原供应商任务；查询不会再次生成图片。',
};

/** 微单位金额只格式化已记录数字，缺少账单时明确未知。 */
function cost(value: number | null, currency: string | null) {
  return value === null ? '未知' : `${(value / 1_000_000).toFixed(6)} ${currency ?? '币种未登记'}`;
}

export default function JobDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const cache = useQueryClient();
  const detail = useQuery({
    queryKey: ['admin', 'job', id],
    queryFn: async () =>
      expectData(
        await api.GET('/api/v1/admin/jobs/{job_id}', { params: { path: { job_id: id } } }),
      ),
  });
  const action = useMutation({
    mutationFn: async (kind: 'reconcile' | 'cancel') => {
      if (!detail.data) throw new Error('请刷新任务详情');
      const options = {
        params: { path: { job_id: id } },
        body: { expected_revision: detail.data.revision },
      };
      return kind === 'reconcile'
        ? expectData(await api.POST('/api/v1/admin/jobs/{job_id}/reconcile', options))
        : expectData(await api.POST('/api/v1/admin/jobs/{job_id}/cancel', options));
    },
    onSuccess(data) {
      cache.setQueryData(['admin', 'job', id], data);
      void cache.invalidateQueries({ queryKey: ['admin', 'jobs'] });
      void cache.invalidateQueries({ queryKey: ['admin', 'overview'] });
      void cache.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
  });
  const data = detail.data;
  const attempt = data?.attempt;
  return (
    <section className="panel job-detail" aria-label="调用详情">
      <div className="job-detail-head">
        <h2>任务与调用证据</h2>
        <button onClick={onClose}>关闭详情</button>
      </div>
      {detail.isLoading ? (
        <State>加载中…</State>
      ) : detail.error ? (
        <State error={detail.error} retry={() => detail.refetch()} />
      ) : (
        data && (
          <>
            <p className="job-detail-id">{data.job.id}</p>
            <p role="status">{reasons[data.recovery_reason] ?? '请刷新查看任务状态。'}</p>
            <dl className="job-facts">
              <div>
                <dt>任务状态</dt>
                <dd>{labels[data.job.status] ?? data.job.status}</dd>
              </div>
              <div>
                <dt>供应商</dt>
                <dd>{data.job.provider_id}</dd>
              </div>
              <div>
                <dt>请求键</dt>
                <dd>{attempt?.request_key ?? '尚未提交'}</dd>
              </div>
              <div>
                <dt>接单凭据</dt>
                <dd>{attempt ? (attempt.receipt_recorded ? '已记录' : '未获得') : '—'}</dd>
              </div>
              <div>
                <dt>外部状态</dt>
                <dd>{attempt ? (labels[attempt.status] ?? attempt.status) : '—'}</dd>
              </div>
              <div>
                <dt>错误分类</dt>
                <dd>{attempt?.error_code ?? data.job.error_code ?? '—'}</dd>
              </div>
              <div>
                <dt>估算费用</dt>
                <dd>
                  {cost(
                    attempt?.estimated_cost_micros ?? null,
                    attempt?.estimated_currency ?? null,
                  )}
                </dd>
              </div>
              <div>
                <dt>确认费用</dt>
                <dd>{cost(attempt?.actual_cost_micros ?? null, attempt?.currency ?? null)}</dd>
              </div>
              <div>
                <dt>观测耗时</dt>
                <dd>
                  {attempt?.latency_ms == null
                    ? '尚无终态'
                    : `${(attempt.latency_ms / 1000).toFixed(1)} 秒`}
                </dd>
              </div>
              <div>
                <dt>用量</dt>
                <dd>
                  {attempt?.usage && Object.keys(attempt.usage).length
                    ? JSON.stringify(attempt.usage)
                    : '未知'}
                </dd>
              </div>
            </dl>
            <p className="job-detail-note">
              估算与确认费用分别记录。没有供应商账单时，费用显示为未知；用户次数返还不代表供应商免费。
            </p>
            {action.error && <State error={action.error} />}
            <div className="job-detail-actions">
              <button
                className="primary"
                disabled={!data.can_reconcile || action.isPending}
                onClick={() => action.mutate('reconcile')}
              >
                {action.isPending ? '处理中…' : '查询原任务'}
              </button>
              {['queued', 'running'].includes(data.job.status) && (
                <button disabled={action.isPending} onClick={() => action.mutate('cancel')}>
                  {data.job.status === 'queued' ? '取消排队并返还' : '记录取消请求'}
                </button>
              )}
              <button
                disabled={action.isPending}
                onClick={() => {
                  action.reset();
                  void detail.refetch();
                }}
              >
                刷新详情
              </button>
            </div>
          </>
        )
      )}
    </section>
  );
}

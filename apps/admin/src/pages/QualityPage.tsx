/** 工单领取后才能读取明确授权的图片；审核只创建待用户确认的补偿卡。 */
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { request } from '@yingxu/api-client';
import { Title } from '../shared/ui';
type Ticket = {
  id: string;
  asset_id: string;
  reference_asset_id: string | null;
  reason: string;
  revision: number;
  status: string;
  assigned_staff_id: string | null;
  review_note: string;
};
export default function QualityPage() {
  const query = useQuery({
    queryKey: ['quality-feedback'],
    queryFn: () => request<Ticket[]>('/admin/quality-feedback'),
    refetchInterval: 10000,
  });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const action = useMutation({
    mutationFn: ({ row, action }: { row: Ticket; action: string }) =>
      request(`/admin/quality-feedback/${row.id}/action`, {
        method: 'POST',
        body: JSON.stringify({
          expected_revision: row.revision,
          action,
          note: notes[row.id] ?? '',
        }),
      }),
    onSuccess: () => query.refetch(),
  });
  return (
    <>
      <Title
        title="质量反馈"
        description="非实时留言 · 指定图片授权 · 每个原作品最多一次补偿"
        onRefresh={() => void query.refetch()}
      />
      {action.error && <p role="alert">{action.error.message}</p>}
      {query.data?.map((row) => (
        <section className="panel" key={row.id}>
          <h2>{row.reason}</h2>
          <p>
            {row.status} · {row.review_note}
          </p>
          {row.status === 'open' ? (
            <button
              disabled={action.isPending}
              onClick={() => action.mutate({ row, action: 'claim' })}
            >
              领取反馈
            </button>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 12 }}>
                {[row.asset_id, row.reference_asset_id].filter(Boolean).map((id) => (
                  <img
                    key={id}
                    width={180}
                    style={{ objectFit: 'contain', maxHeight: 260 }}
                    src={`/api/v1/admin/quality-feedback/${row.id}/assets/${id}`}
                    alt={id === row.asset_id ? '授权成片' : '单独授权参考照'}
                  />
                ))}
              </div>
              <label>
                人工判断与补偿理由
                <textarea
                  value={notes[row.id] ?? ''}
                  onChange={(event) => setNotes({ ...notes, [row.id]: event.target.value })}
                />
              </label>
              {row.status !== 'approved' && (
                <button
                  disabled={action.isPending || (notes[row.id]?.trim().length ?? 0) < 3}
                  onClick={() => action.mutate({ row, action: 'approve_redo' })}
                >
                  批准一次补偿，等待用户确认
                </button>
              )}
              <button
                disabled={action.isPending}
                onClick={() => action.mutate({ row, action: 'close' })}
              >
                结单并停止看图授权
              </button>
            </>
          )}
        </section>
      ))}
    </>
  );
}

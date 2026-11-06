/** 用户指定作品反馈，参考照另选授权，补偿也必须明确点击一次。 */
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { request, assetUrl, type Asset, type Plan } from '@yingxu/api-client';
type Ticket = {
  id: string;
  reason: string;
  status: string;
  revision: number;
  grant_active: boolean;
  review_note: string;
  plan: Plan | null;
};
export default function QualityFeedback({
  projectId,
  assetId,
  assets,
  refresh,
}: {
  projectId: string;
  assetId: string;
  assets: Asset[];
  refresh: () => void;
}) {
  const [reason, setReason] = useState('');
  const [reference, setReference] = useState('');
  const [consent, setConsent] = useState(false);
  const query = useQuery({
    queryKey: ['feedback', projectId],
    queryFn: () =>
      request<(Ticket & { asset_id: string })[]>(`/web/projects/${projectId}/feedback`),
    refetchInterval: 15000,
  });
  const row = query.data?.find((item) => item.asset_id === assetId);
  const save = useMutation({
    mutationFn: () =>
      request(`/web/projects/${projectId}/feedback`, {
        method: 'POST',
        body: JSON.stringify({
          asset_id: assetId,
          reference_asset_id: reference || null,
          reason,
          grant_view: consent,
        }),
      }),
    onSuccess: () => query.refetch(),
  });
  const withdraw = useMutation({
    mutationFn: () =>
      request(`/web/quality-feedback/${row!.id}/action`, {
        method: 'POST',
        body: JSON.stringify({ expected_revision: row!.revision, action: 'withdraw' }),
      }),
    onSuccess: () => query.refetch(),
  });
  const accept = useMutation({
    mutationFn: () =>
      request(`/web/approvals/${row!.plan!.approval_id}/accept`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `compensation-${row!.plan!.approval_id}` },
      }),
    onSuccess: () => {
      void query.refetch();
      refresh();
    },
  });
  return (
    <details>
      <summary>质量反馈 / 补偿</summary>
      {row ? (
        <>
          <p>
            {row.reason} · {row.status}
          </p>
          <p>{row.review_note}</p>
          {row.grant_active && (
            <button disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>
              撤回看图授权
            </button>
          )}
          {row.plan && row.status === 'approved' && row.grant_active && (
            <div className="cx-confirmation-card">
              <h3>补偿重做确认</h3>
              <p>
                沿用这张原作品的冻结输入和模型，生成 1
                张；不消耗新增次数。原作品保留，仍会产生供应商成本。
              </p>
              <p>
                {row.plan.spec_json.style_name} · {row.plan.spec_json.aspect_ratio} ·{' '}
                {row.plan.spec_json.notes}
              </p>
              <div className="cx-confirm-inputs">
                {(row.plan.spec_json.items?.[0]?.inputs ?? [])
                  .filter((input) => input.source === 'catalog')
                  .map((input, index) => (
                    <figure key={`catalog-${index}`}>
                      <img
                        src={`/api/v1/web/inspiration/${encodeURIComponent(input.style_id!)}/${encodeURIComponent(input.shot_id!)}/content`}
                        alt={input.role === 'base' ? '原镜头底图' : '风格参考'}
                      />
                      <figcaption>{input.role === 'base' ? '原镜头底图' : '风格参考'}</figcaption>
                    </figure>
                  ))}
                {assets
                  .filter(
                    (asset) =>
                      (row.plan!.spec_json.reference_asset_ids ?? []).includes(asset.id) ||
                      row.plan!.spec_json.base_asset_id === asset.id,
                  )
                  .map((asset) => (
                    <figure key={asset.id}>
                      <img
                        src={assetUrl(asset.id)}
                        alt={asset.kind === 'reference' ? '人物参考' : '底图'}
                      />
                      <figcaption>{asset.kind === 'reference' ? '人物参考' : '底图'}</figcaption>
                    </figure>
                  ))}
              </div>
              {row.plan.spec_json.mode === 'edit' && (
                <p>
                  保留：{(row.plan.spec_json.keep ?? []).join('、')}；修改：
                  {row.plan.spec_json.change}
                </p>
              )}
              <button
                disabled={accept.isPending || row.plan.approval_status !== 'pending'}
                onClick={() => accept.mutate()}
              >
                {row.plan.approval_status === 'accepted'
                  ? '已确认补偿'
                  : '确认补偿重做 · 1 张 / 0 次'}
              </button>
            </div>
          )}
        </>
      ) : (
        <>
          <label>
            哪里不满意？
            <textarea
              maxLength={1000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <label>
            额外授权一张参考照（可选）
            <select
              value={reference}
              onChange={(event) => {
                setReference(event.target.value);
                setConsent(false);
              }}
            >
              <option value="">只允许看这张成片</option>
              {assets
                .filter((asset) => asset.kind === 'reference')
                .map((asset, index) => (
                  <option key={asset.id} value={asset.id}>
                    人物参考 {index + 1}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => setConsent(event.target.checked)}
            />
            允许处理此反馈的工作人员查看这张成片{reference ? '与所选的一张参考照' : ''}
            。可撤回，结单后失效，最长30天。
          </label>
          <button
            disabled={!consent || reason.trim().length < 3 || save.isPending}
            onClick={() => save.mutate()}
          >
            提交非实时质量反馈
          </button>
        </>
      )}
      {(save.error || withdraw.error || accept.error) && (
        <p role="alert">{(save.error || withdraw.error || accept.error)?.message}</p>
      )}
    </details>
  );
}

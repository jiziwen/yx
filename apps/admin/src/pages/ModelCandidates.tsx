/** 候选与实测证据分离，只有管理员明确审核才启用。 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { request, type ModelSettings } from '@yingxu/api-client';
import { modelCandidatesQuery, type ModelCandidate } from '../features/models/candidates';
import { State } from '../shared/ui';

export default function ModelCandidates({
  revision,
  onLoad,
  onActivated,
  saving,
}: {
  revision: number;
  onLoad: (candidate: ModelCandidate) => void;
  onActivated: (settings: ModelSettings) => void;
  saving: boolean;
}) {
  const cache = useQueryClient();
  const query = useQuery(modelCandidatesQuery);
  const [selected, setSelected] = useState<ModelCandidate | null>(null);
  const [cases, setCases] = useState<Record<string, string>>({});
  const [cost, setCost] = useState('');
  const [bill, setBill] = useState('');
  const [note, setNote] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [activated, setActivated] = useState<number | null>(null);
  const activate = useMutation({
    mutationFn: () =>
      request<ModelSettings>(`/admin/model-candidates/${selected!.id}/activate`, {
        method: 'POST',
        body: JSON.stringify({
          expected_revision: revision,
          candidate_digest: selected!.digest,
          cases,
          actual_cost_cny: Number(cost),
          bill_reference: bill,
          review_note: note,
          confirmed,
        }),
      }),
    onSuccess: (settings) => {
      setSelected(null);
      setActivated(settings.revision);
      onActivated(settings);
      void cache.invalidateQueries({ queryKey: modelCandidatesQuery.queryKey });
      void cache.invalidateQueries({ queryKey: ['admin', 'model-settings'] });
      void cache.invalidateQueries({ queryKey: ['admin-catalog'] });
      void cache.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
  });
  const requirements = selected?.required_cases ?? [];
  return (
    <section className="panel model-candidates" id="model-candidates">
      <div className="model-candidates-heading">
        <div>
          <h2>候选与启用审核</h2>
          <p className="model-help">
            保存的配置在这里。完成对应能力实测，填写记录和费用后即可审核启用。
          </p>
        </div>
        <span className="badge">{query.data?.length ?? 0} 个候选</span>
      </div>
      {activated !== null && (
        <p className="model-feedback success" role="status">
          已启用版本 v{activated}，配置表单已同步。
        </p>
      )}
      {query.isLoading ? (
        <State>正在读取候选…</State>
      ) : query.error ? (
        <State error={query.error} retry={() => void query.refetch()} />
      ) : !query.data?.length ? (
        <p className="model-candidates-empty">暂无候选，填写上方配置后点击“保存为候选新版本”。</p>
      ) : (
        <div className="model-candidate-list">
          {query.data.map((row) => (
            <article
              key={row.id}
              className="model-candidate-row"
              data-selected={selected?.id === row.id}
            >
              <div className="model-candidate-summary">
                <div>
                  <code>{row.digest.slice(0, 12)}</code>
                  <span className={'badge ' + (row.status === 'approved' ? 'active' : 'queued')}>
                    {row.status === 'approved' ? '已审核' : '待实测'}
                  </span>
                </div>
                <p>
                  图片：{row.settings_json.image.text_model} · {row.settings_json.image.quality}
                </p>
                <p>
                  语言：{row.settings_json.llm.model} · 视觉：
                  {row.settings_json.vision?.enabled ? row.settings_json.vision.model : '关闭'}
                </p>
              </div>
              <div className="model-candidate-actions">
                <button
                  type="button"
                  className="outline"
                  disabled={saving || activate.isPending}
                  onClick={() => onLoad(row)}
                >
                  载入配置
                </button>
                <button
                  type="button"
                  className="outline"
                  disabled={saving || activate.isPending}
                  onClick={() => {
                    setSelected(row);
                    setActivated(null);
                    setCases({});
                    setConfirmed(false);
                    setCost('');
                    setBill('');
                    setNote('');
                    activate.reset();
                  }}
                >
                  查看 / 审核启用{row.status === 'approved' ? '（可回退）' : ''}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      {selected && (
        <form
          className="model-review"
          onSubmit={(event) => {
            event.preventDefault();
            activate.mutate();
          }}
        >
          <div className="model-candidates-heading">
            <h3>
              审核候选 <code>{selected.digest.slice(0, 12)}</code>
            </h3>
            <button
              type="button"
              className="outline"
              disabled={activate.isPending}
              onClick={() => setSelected(null)}
            >
              收起审核
            </button>
          </div>
          <details className="model-candidate-details">
            <summary>查看完整配置</summary>
            <pre>{JSON.stringify(selected.settings_json, null, 2)}</pre>
          </details>
          <p className="model-help">请填写真实实测记录；此处不会自动发送收费测试。</p>
          <fieldset disabled={activate.isPending}>
            <div className="model-form-grid">
              {requirements.map((key) => (
                <label key={key} className="model-field-wide">
                  {key} 实测记录位置与结论
                  <input
                    required
                    minLength={3}
                    maxLength={300}
                    value={cases[key] ?? ''}
                    onChange={(event) => setCases({ ...cases, [key]: event.target.value })}
                  />
                </label>
              ))}
              <label>
                本次已核对实际费用（人民币）
                <input
                  required
                  type="number"
                  min="0"
                  step="0.0001"
                  value={cost}
                  onChange={(event) => setCost(event.target.value)}
                />
              </label>
              <label>
                账单记录位置
                <input
                  required
                  minLength={3}
                  maxLength={300}
                  value={bill}
                  onChange={(event) => setBill(event.target.value)}
                />
              </label>
              <label className="model-field-wide">
                人工验收结论
                <textarea
                  required
                  minLength={3}
                  maxLength={1000}
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </label>
            </div>
            <label className="model-toggle model-review-confirm">
              <input
                type="checkbox"
                required
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              我已核对该候选所有启用能力的效果、输入限制及实际费用，批准切换。
            </label>
            <button
              className="primary"
              disabled={!confirmed || !cost || activate.isPending || saving}
            >
              {activate.isPending ? '启用中…' : '批准并启用候选'}
            </button>
          </fieldset>
          {activate.error && (
            <p className="model-feedback error" role="alert">
              启用失败：{activate.error.message}
            </p>
          )}
        </form>
      )}
    </section>
  );
}

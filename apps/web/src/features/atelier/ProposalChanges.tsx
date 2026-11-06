/** 对比发送时冻结的原草稿；不把等待期间的新编辑当成可覆盖的基线。 */
import type { AgentDraftPatch, AgentRun } from '@yingxu/api-client';

const fields: Record<Exclude<keyof AgentDraftPatch, 'intent'>, string> = {
  mode: '创作方式',
  subject_only: '只替换人物并保留底图',
  shot_ids: '镜头底图',
  style_shot_ids: '风格参考',
  reference_asset_ids: '人物参考',
  base_asset_id: '修改底图',
  style_id: '主题套系',
  aspect_ratio: '画幅',
  count: '成片张数',
  variants: '每个镜头版本',
  mood: '画面氛围',
  notes: '创作要求',
  change: '调整细节',
  keep: '保留内容',
};
const modes: Record<string, string> = {
  template: '拍同款',
  portrait: '人物写真',
  edit: '修改照片',
  text: '文生图',
};

export default function ProposalChanges({
  proposal,
  original,
  styles,
}: {
  proposal: AgentDraftPatch;
  original: AgentRun['draft_context'];
  styles: { id: string; name: string }[];
}) {
  const value = (name: string, item: unknown) => {
    if (item == null) return '未记录';
    if (name === 'mode') return modes[String(item)] ?? String(item);
    if (name === 'style_id') return styles.find((style) => style.id === item)?.name ?? String(item);
    if (Array.isArray(item)) return item.join('、') || '未设置';
    return String(item).trim() || '未填写';
  };
  const entries = (Object.keys(fields) as Exclude<keyof AgentDraftPatch, 'intent'>[]).filter(
    (name) => proposal[name] != null,
  );
  const changed = entries.filter(
    (name) => JSON.stringify(original?.[name]) !== JSON.stringify(proposal[name]),
  );
  const unchanged = entries.filter((name) => !changed.includes(name));
  return (
    <div className="at-proposal-changes">
      <p>与发送需求时的草稿对比 · {changed.length} 项调整</p>
      {changed.length > 0 ? (
        <dl>
          {changed.map((name) => (
            <div key={name} className="at-proposal-change">
              <dt>{fields[name]}</dt>
              <dd>
                <span className="at-proposal-before">
                  <small>原草稿</small>
                  {value(name, original?.[name])}
                </span>
                <span className="at-proposal-after">
                  <small>建议修改</small>
                  {value(name, proposal[name])}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p>提案中的字段与原草稿一致。</p>
      )}
      {unchanged.length > 0 && (
        <details>
          <summary>沿用 {unchanged.length} 项原设置</summary>
          <dl>
            {unchanged.map((name) => (
              <div key={name}>
                <dt>{fields[name]}</dt>
                <dd>{value(name, proposal[name])}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}

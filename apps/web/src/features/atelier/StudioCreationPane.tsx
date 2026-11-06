/** 四种模式只显示当前必要素材；所有修改共用草稿，上传和生成各自校验授权。 */
import { useEffect, useState, type ReactNode } from 'react';
import { assetUrl, type Asset, type Catalog, type Subject } from '@yingxu/api-client';
import {
  ChevronRight,
  ImagePlus,
  Paperclip,
  Sparkles,
  SlidersHorizontal,
  Upload,
} from 'lucide-react';
import SubjectPanel from '../projects/SubjectPanel';
import StudioDialog from './StudioDialog';
import { creationModes } from './creationModes';
import { describeDraft, type CreationDraft } from './creationDraft';

export type MaterialKind =
  | 'people'
  | 'shots'
  | 'style'
  | 'base'
  | 'idea'
  | 'details'
  | 'attachments';
const titles: Record<MaterialKind, string> = {
  people: '人物参考',
  shots: '样片底图',
  style: '风格参考图（选填）',
  base: '待修改照片',
  idea: '这次的创意',
  details: '创作细节',
  attachments: '照片用在哪里？',
};
const hints: Record<string, string> = {
  template: '样片做底图，人物照只用来替换主角。',
  portrait: '用人物参考照，设计新的画面。',
  edit: '只需要一张底图，告诉 Lumi 想改哪里。',
  text: '无需图片，从一句话开始创作。',
};
export default function StudioCreationPane({
  projectId,
  kind,
  draft,
  catalog,
  assets,
  subjects,
  readonly,
  onChange,
  onUpload,
  onUploaded,
  refresh,
  confirmation,
  materialRequest,
}: {
  projectId: string;
  kind: string;
  draft: CreationDraft;
  catalog: Catalog;
  assets: Asset[];
  subjects: Subject[];
  readonly: boolean;
  onChange: (patch: Partial<CreationDraft>) => void;
  onUpload: (file: File, purpose: 'base' | 'style') => void;
  onUploaded: (asset: Asset) => void;
  refresh: () => void;
  confirmation: ReactNode;
  materialRequest?: { kind: MaterialKind; nonce: number };
}) {
  const [dialog, setDialog] = useState<MaterialKind | null>(null);
  const [consent, setConsent] = useState(false);
  const state = describeDraft(draft, catalog, assets, subjects);
  const styles = catalog.styles.filter((style) => style.kind === kind);
  useEffect(() => {
    if (materialRequest) setDialog(materialRequest.kind);
  }, [materialRequest]);
  useEffect(() => setConsent(false), [dialog]);
  const toggle = (
    field: 'reference_asset_ids' | 'shot_ids' | 'style_shot_ids' | 'style_asset_ids',
    id: string,
  ) =>
    onChange({
      [field]: (draft[field] ?? []).includes(id)
        ? draft[field].filter((value) => value !== id)
        : [...(draft[field] ?? []), id],
    });
  const image =
    draft.mode === 'template'
      ? state.shots[0]?.image
      : draft.mode === 'edit'
        ? state.base && assetUrl(state.base.id)
        : draft.mode === 'portrait'
          ? state.style?.image
          : undefined;
  const imageLabel =
    draft.mode === 'template'
      ? '样片底图'
      : draft.mode === 'edit'
        ? '当前底图'
        : '风格示意 · 不自动发送';
  const ratioLabel =
    draft.aspect_ratio !== 'auto'
      ? `输出 ${draft.aspect_ratio}`
      : ['template', 'edit'].includes(draft.mode)
        ? `跟随原图${state.ratios.length ? ' · ' + state.ratios.join(' / ') : ''}`
        : '默认 3:4';
  const open = (type: MaterialKind) => setDialog(type);
  const material = (
    type: MaterialKind,
    label: string,
    caption: string,
    src?: string,
    optional = false,
  ) => (
    <button
      type="button"
      className={'sx-material' + (optional ? ' sx-optional' : '')}
      disabled={readonly}
      onClick={() => open(type)}
      aria-label={label}
    >
      {src ? <img src={src} alt="" /> : <ImagePlus size={22} />}
      <span className="sx-material-info">
        <strong>{label}</strong>
        <small>{caption}</small>
      </span>
      <ChevronRight size={14} />
    </button>
  );
  const allowedShot = (development: boolean, approved: boolean) =>
    state.capability?.development_sample || (!development && approved);
  const shotPicker = (field: 'shot_ids' | 'style_shot_ids') => (
    <>
      <label className="sx-field">
        选择套系
        <select
          aria-label="创作风格"
          value={draft.style_id}
          onChange={(event) => {
            const style = styles.find((entry) => entry.id === event.target.value);
            onChange({
              style_id: event.target.value,
              shot_ids:
                draft.mode === 'template'
                  ? (style?.shots.slice(0, 1).map((shot) => shot.id) ?? [])
                  : [],
              style_shot_ids: [],
            });
          }}
        >
          {styles.map((style) => (
            <option key={style.id} value={style.id}>
              {style.name}
            </option>
          ))}
        </select>
      </label>
      <div className="sx-photo-grid">
        {state.style?.shots.map((shot, index) => (
          <button
            type="button"
            key={shot.id}
            aria-label={`${field === 'shot_ids' ? '使用底图' : '使用风格参考'} ${index + 1}`}
            aria-pressed={draft[field].includes(shot.id)}
            disabled={readonly || !allowedShot(shot.development_only, shot.rights_approved)}
            onClick={() => toggle(field, shot.id)}
          >
            <img src={shot.image} alt={shot.name} style={{ objectPosition: shot.position }} />
            <span>
              {shot.name}
              {!allowedShot(shot.development_only, shot.rights_approved) ? ' · 仅展示' : ''}
            </span>
          </button>
        ))}
      </div>
    </>
  );
  const upload = (purpose: 'base' | 'style') => (
    <div className="sx-upload">
      <label className="sx-check">
        <input
          type="checkbox"
          aria-label={purpose === 'base' ? '底图使用声明' : '风格参考使用声明'}
          checked={consent}
          disabled={readonly}
          onChange={(event) => setConsent(event.target.checked)}
        />
        我有权使用这张照片进行创作。
      </label>
      <label className="sx-button">
        <Upload size={15} />
        上传{purpose === 'base' ? '底图' : '风格参考图'}
        <input
          type="file"
          aria-label={purpose === 'base' ? '上传修改底图' : '上传风格参考图'}
          accept="image/jpeg,image/png,image/webp"
          disabled={readonly || !consent}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file, purpose);
            event.target.value = '';
          }}
        />
      </label>
      <small>
        JPG / PNG / WebP · 最多 {Math.floor(catalog.upload_limits.max_bytes / 1024 / 1024)} MB
      </small>
    </div>
  );
  return (
    <div className="sx-creation-pane cx-creation-pane">
      <fieldset disabled={readonly}>
        <div className="sx-modes" aria-label="创作模式">
          {creationModes
            .filter((mode) => catalog.creation_modes.some((item) => item.id === mode.id))
            .map((mode) => (
              <button
                key={mode.id}
                className="sx-mode"
                type="button"
                aria-pressed={draft.mode === mode.id}
                onClick={() => onChange({ mode: mode.id })}
              >
                <mode.icon size={15} />
                {mode.short}
              </button>
            ))}
        </div>
        <p className="sx-mode-hint">{hints[draft.mode]}</p>
        <div className="sx-materials" aria-label="当前模式素材">
          {draft.mode === 'template' &&
            material(
              'shots',
              '样片底图',
              `${state.shots.length} 个镜头已选`,
              state.shots[0]?.image,
            )}
          {state.refsActive &&
            material(
              'people',
              '人物参考',
              `${state.references.length} 张 · ${state.people.map((person) => person.display_name).join('、') || '选择或添加人物'}`,
              state.references[0] && assetUrl(state.references[0].id),
            )}
          {draft.mode === 'portrait' &&
            material(
              'style',
              '风格参考图（选填）',
              state.styleShots.length + state.styleAssets.length
                ? `已选 ${state.styleShots.length + state.styleAssets.length} 张 · 仅参考风格`
                : '选填 · 不复刻构图',
              state.styleShots[0]?.image ??
                (state.styleAssets[0] && assetUrl(state.styleAssets[0].id)),
              !state.styleShots.length && !state.styleAssets.length,
            )}
          {draft.mode === 'edit' &&
            material(
              'base',
              '待修改照片',
              state.base ? '1 张底图 · 点击更换' : '选择已有照片或上传',
              state.base && assetUrl(state.base.id),
            )}
          {draft.mode === 'text' && (
            <label className="sx-text-prompt">
              画面描述
              <textarea
                aria-label="你心里的画面"
                rows={2}
                maxLength={1000}
                value={draft.notes}
                onChange={(event) => onChange({ notes: event.target.value })}
                placeholder="把你心里的画面告诉 Lumi，或在这里写下…"
              />
            </label>
          )}
        </div>
      </fieldset>
      <div className="sx-canvas-section">
        <div className="sx-canvas-heading">
          <h2>{draft.mode === 'edit' ? '当前底图' : '这次的画面'}</h2>
          <small>先定方向，再生成</small>
        </div>
        <div className="sx-image-canvas">
          {image ? (
            <>
              <img src={image} alt={draft.mode === 'edit' ? '本次准备修改的底图' : imageLabel} />
              <span>{imageLabel}</span>
            </>
          ) : (
            <div className="sx-empty-canvas">
              <Sparkles size={26} />
              <strong>
                {draft.mode === 'text'
                  ? '从一句话开始'
                  : draft.mode === 'edit'
                    ? '放入一张想修改的照片'
                    : '选择素材，开始你的创作'}
              </strong>
              <p>
                {draft.mode === 'text'
                  ? '不使用项目照片，画面中的人物由模型创作。'
                  : '选好素材后，在左侧告诉 Lumi 你的想法。'}
              </p>
            </div>
          )}
        </div>
        {draft.mode !== 'text' && (
          <div className="sx-idea-line">
            <p>
              {draft.mode === 'edit'
                ? draft.change
                : draft.mode === 'template' && draft.subject_only
                  ? '保留底图站位、姿势、构图和色调，只替换人物。'
                  : draft.notes || '把想法告诉 Lumi，也可以直接补充要求。'}
            </p>
            <button type="button" disabled={readonly} onClick={() => open('idea')}>
              编辑创意
            </button>
          </div>
        )}
      </div>
      <div className="sx-generate-row">
        <div>
          <fieldset className="sx-settings" disabled={readonly}>
            <select
              aria-label="画幅"
              value={draft.aspect_ratio}
              onChange={(event) => onChange({ aspect_ratio: event.target.value })}
            >
              <option value="auto">
                {['template', 'edit'].includes(draft.mode) ? '跟随原图' : '自动（3:4）'}
              </option>
              {[
                ...new Set([
                  ...catalog.aspect_ratios,
                  ...(draft.aspect_ratio !== 'auto' ? [draft.aspect_ratio] : []),
                ]),
              ].map((ratio) => (
                <option key={ratio} value={ratio}>
                  {ratio === '16:9' ? '横屏 ' : ratio === '9:16' ? '竖屏 ' : ''}
                  {ratio}
                </option>
              ))}
            </select>
            <select
              aria-label={draft.mode === 'template' ? '每个镜头版本数' : '成片张数'}
              value={draft.mode === 'template' ? draft.variants : draft.count}
              onChange={(event) =>
                onChange(
                  draft.mode === 'template'
                    ? { variants: Number(event.target.value) }
                    : { count: Number(event.target.value) },
                )
              }
            >
              {Array.from({ length: catalog.max_count }, (_, i) => i + 1).map((count) => (
                <option key={count} value={count}>
                  {draft.mode === 'template' ? '每镜头 ' : ''}
                  {count} 张
                </option>
              ))}
            </select>
            <button type="button" className="sx-detail-trigger" onClick={() => open('details')}>
              <SlidersHorizontal size={14} />
              细节
            </button>
          </fieldset>
          <p className="sx-output-meta">
            {ratioLabel} · 生成 {state.count} 张
          </p>
        </div>
        {confirmation}
      </div>
      {dialog && (
        <StudioDialog title={titles[dialog]} onClose={() => setDialog(null)}>
          <fieldset disabled={readonly}>
            {dialog === 'attachments' && (
              <div className="sx-attachment-roles">
                {(['people', 'base', 'style'] as const).map((type) => (
                  <button
                    type="button"
                    className="sx-button"
                    key={type}
                    onClick={() => {
                      if (type === 'base') onChange({ mode: 'edit' });
                      else if ((type === 'people' && !state.refsActive) || type === 'style')
                        onChange({ mode: 'portrait' });
                      setDialog(type);
                    }}
                  >
                    <Paperclip size={15} />
                    {type === 'people'
                      ? '作为人物参考'
                      : type === 'base'
                        ? '作为待修改底图'
                        : '只参考风格氛围'}
                  </button>
                ))}
              </div>
            )}
            {dialog === 'people' && (
              <>
                <div className="sx-photo-grid">
                  {assets
                    .filter(
                      (asset) =>
                        asset.kind === 'reference' &&
                        subjects.some(
                          (subject) =>
                            subject.id === asset.subject_id &&
                            subject.authorization_state === 'declared',
                        ),
                    )
                    .map((asset, index) => (
                      <button
                        type="button"
                        key={asset.id}
                        aria-pressed={draft.reference_asset_ids.includes(asset.id)}
                        aria-label={`选择参考照片：${subjects.find((subject) => subject.id === asset.subject_id)?.display_name} ${index + 1}`}
                        onClick={() => toggle('reference_asset_ids', asset.id)}
                      >
                        <img src={assetUrl(asset.id)} alt="人物参考照片" />
                        <span>
                          {
                            subjects.find((subject) => subject.id === asset.subject_id)
                              ?.display_name
                          }{' '}
                          · {index + 1}
                        </span>
                      </button>
                    ))}
                </div>
                <details
                  open={!subjects.length || !assets.some((asset) => asset.kind === 'reference')}
                >
                  <summary>添加或管理人物参考</summary>
                  <SubjectPanel
                    projectId={projectId}
                    kind={kind}
                    subjects={subjects}
                    assets={assets}
                    readonly={readonly}
                    refresh={refresh}
                    onUploaded={onUploaded}
                  />
                </details>
              </>
            )}
            {dialog === 'shots' && shotPicker('shot_ids')}
            {dialog === 'style' && (
              <>
                <p className="sx-modal-note">只借鉴色调、光线和整体风格，不照搬构图或替换人物。</p>
                {shotPicker('style_shot_ids')}
                <div className="sx-photo-grid">
                  {assets
                    .filter((asset) => asset.kind === 'style')
                    .map((asset, index) => (
                      <button
                        type="button"
                        key={asset.id}
                        aria-label={`选择风格参考 ${index + 1}`}
                        aria-pressed={draft.style_asset_ids?.includes(asset.id)}
                        onClick={() => toggle('style_asset_ids', asset.id)}
                      >
                        <img src={assetUrl(asset.id)} alt="私有风格参考" />
                        <span>我的风格参考 {index + 1}</span>
                      </button>
                    ))}
                </div>
                {upload('style')}
                <button
                  type="button"
                  className="sx-text-button"
                  onClick={() => onChange({ style_shot_ids: [], style_asset_ids: [] })}
                >
                  不使用风格参考图
                </button>
              </>
            )}
            {dialog === 'base' && (
              <>
                <div className="sx-photo-grid">
                  {assets
                    .filter((asset) => ['base', 'photo'].includes(asset.kind))
                    .map((asset, index) => (
                      <button
                        type="button"
                        key={asset.id}
                        aria-label={`选择项目底图 ${index + 1}`}
                        aria-pressed={draft.base_asset_id === asset.id}
                        onClick={() => onChange({ base_asset_id: asset.id })}
                      >
                        <img src={assetUrl(asset.id)} alt="可选底图" />
                        <span>
                          {asset.kind === 'photo' ? '已有成片' : '我的底图'} {index + 1}
                        </span>
                      </button>
                    ))}
                </div>
                {upload('base')}
              </>
            )}
            {dialog === 'idea' && (
              <>
                <label className="sx-field">
                  {draft.mode === 'edit' ? '想调整哪里' : '补充要求'}
                  <textarea
                    rows={4}
                    maxLength={1000}
                    aria-label={draft.mode === 'edit' ? '想调整哪里' : '补充要求'}
                    value={draft.mode === 'edit' ? draft.change : draft.notes}
                    onChange={(event) =>
                      onChange(
                        draft.mode === 'edit'
                          ? { change: event.target.value }
                          : {
                              notes: event.target.value,
                              ...(draft.mode === 'template' ? { subject_only: false } : {}),
                            },
                      )
                    }
                  />
                </label>
                <label className="sx-field">
                  画面氛围
                  <input
                    maxLength={120}
                    aria-label="画面氛围"
                    value={draft.mood}
                    onChange={(event) => onChange({ mood: event.target.value })}
                  />
                </label>
              </>
            )}
            {dialog === 'details' && (
              <>
                {draft.mode === 'template' && (
                  <>
                    <label className="sx-check">
                      <input
                        type="checkbox"
                        aria-label="只替换人物，保留底图其他细节"
                        checked={draft.subject_only}
                        onChange={(event) => onChange({ subject_only: event.target.checked })}
                      />
                      只替换人物，保留底图其他细节
                    </label>
                    {state.people.map((subject) => (
                      <label className="sx-field" key={subject.id}>
                        {subject.display_name}对应底图位置
                        <select
                          aria-label={subject.display_name + '对应底图位置'}
                          value={
                            state.bindings.find((binding) => binding.subject_id === subject.id)
                              ?.position ?? ''
                          }
                          onChange={(event) =>
                            onChange({
                              positions: {
                                ...draft.positions,
                                [subject.id]: event.target.value as 'only' | 'left' | 'right',
                              },
                            })
                          }
                        >
                          <option value="" disabled>
                            请选择位置
                          </option>
                          {state.slots.map((slot) => (
                            <option key={slot} value={slot}>
                              {slot === 'only'
                                ? '唯一主角'
                                : slot === 'left'
                                  ? '左侧主角'
                                  : '右侧主角'}
                            </option>
                          ))}
                        </select>
                      </label>
                    ))}
                  </>
                )}
                {draft.mode === 'edit' && (
                  <div className="sx-keep">
                    保留哪些部分
                    {(['场景与构图', '人物与表情', '服装与造型'] as const).map((value) => (
                      <label className="sx-check" key={value}>
                        <input
                          type="checkbox"
                          checked={draft.keep.includes(value)}
                          onChange={(event) =>
                            onChange({
                              keep: event.target.checked
                                ? [...draft.keep, value]
                                : draft.keep.filter((item) => item !== value),
                            })
                          }
                        />
                        {value}
                      </label>
                    ))}
                  </div>
                )}
                <p className="sx-modal-note">
                  {draft.mode === 'text'
                    ? '只发送文字，不携带项目照片。'
                    : `每个任务使用 ${state.inputs} 张图片；当前模型上限 ${state.capability?.max_input_images ?? 0} 张。`}
                </p>
                <button type="button" className="sx-button" onClick={() => open('idea')}>
                  编辑创意要求
                </button>
              </>
            )}
          </fieldset>
        </StudioDialog>
      )}
    </div>
  );
}

/** 正式草稿与模型输入编译；界面提示来自公开能力，服务端仍作最终校验。 */
import type { Asset, Catalog, Plan, PlanInput, Subject } from '@yingxu/api-client';
import type { CreativeEntry } from '../../app/context';
import type { CreationMode } from './creationModes';

export type Style = Catalog['styles'][number];
export interface CreationDraft {
  mode: CreationMode;
  subject_only: boolean;
  style_id: string;
  aspect_ratio: string;
  count: number;
  mood: string;
  notes: string;
  reference_asset_ids: string[];
  base_asset_id: string | null;
  shot_ids: string[];
  style_shot_ids: string[];
  style_asset_ids: string[];
  variants: number;
  keep: ('场景与构图' | '人物与表情' | '服装与造型')[];
  change: string;
  positions: Record<string, 'left' | 'right' | 'only'>;
}

/** 首次载入兼容历史规格，显式入场意图优先，刷新不覆盖已有编辑。 */
export function initialDraft(
  styles: Style[],
  catalog: Catalog,
  assets: Asset[],
  saved?: Plan,
  entry?: CreativeEntry | null,
): CreationDraft {
  const spec = saved?.spec_json;
  const style = styles.find((item) => item.id === (entry?.styleId ?? spec?.style_id)) ?? styles[0];
  const preferred = (entry?.mode ?? spec?.mode ?? 'portrait') as CreationMode;
  const mode = catalog.creation_modes.some((item) => item.id === preferred)
    ? preferred
    : ((catalog.creation_modes[0]?.id ?? 'portrait') as CreationMode);
  return {
    mode,
    subject_only: spec?.subject_only ?? mode === 'template',
    style_id: style?.id ?? '',
    aspect_ratio: spec?.aspect_ratio_choice ?? spec?.aspect_ratio ?? 'auto',
    count: spec?.count ?? 1,
    mood: spec?.mood ?? style?.mood ?? '自然柔光',
    notes: entry?.brief ?? spec?.notes ?? '',
    reference_asset_ids:
      spec?.schema_version === 1
        ? assets.filter((asset) => asset.kind === 'reference').map((asset) => asset.id)
        : (spec?.reference_asset_ids ?? []),
    base_asset_id: spec?.base_asset_id ?? null,
    shot_ids:
      entry?.shotIds ?? spec?.shot_ids ?? style?.shots.slice(0, 1).map((shot) => shot.id) ?? [],
    style_shot_ids: entry?.styleShotIds ?? spec?.style_shot_ids ?? [],
    style_asset_ids: spec?.style_asset_ids ?? [],
    variants: spec?.variants ?? 1,
    keep: (spec?.keep ?? ['场景与构图']) as CreationDraft['keep'],
    change: spec?.change ?? '光线更柔和，色调温暖一点',
    positions: Object.fromEntries(
      (spec?.subject_bindings ?? [])
        .filter((binding) => ['left', 'right', 'only'].includes(binding.position))
        .map((binding) => [binding.subject_id, binding.position]),
    ) as CreationDraft['positions'],
  };
}

/** 自动画幅只继承底图，不从人物或风格参考推断。未知历史样片尺寸交给后端核对。 */
export function outputRatios(draft: CreationDraft, style: Style | undefined, assets: Asset[]) {
  if (draft.aspect_ratio !== 'auto') return [draft.aspect_ratio];
  const dimensions =
    draft.mode === 'template'
      ? (style?.shots.filter((shot) => draft.shot_ids.includes(shot.id)) ?? [])
      : draft.mode === 'edit'
        ? assets.filter((asset) => asset.id === draft.base_asset_id)
        : [];
  if (!['template', 'edit'].includes(draft.mode)) return ['3:4'];
  const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a);
  return [
    ...new Set(
      dimensions.flatMap(({ width, height }) => {
        if (!width || !height) return [];
        const divisor = gcd(width, height);
        return [`${width / divisor}:${height / divisor}`];
      }),
    ),
  ];
}

export const subjectOnlyNotes =
  '只替换为已选人物参考中的人物；保留底图人物站位、朝向、姿势、画面占比、构图、背景、服装和色调，不镜像、不拉近或重新构图。';

/** 聊天和右侧按钮共用模式转换，选中的目录图随用途迁移，私有人物参考不丢失。 */
export function transitionDraft(
  current: CreationDraft,
  patch: Partial<CreationDraft>,
): CreationDraft {
  const next = { ...current, ...patch };
  const changed = next.mode !== current.mode;
  if (changed) {
    const selected =
      current.mode === 'portrait' && current.style_shot_ids.length
        ? current.style_shot_ids
        : current.shot_ids.length
          ? current.shot_ids
          : current.style_shot_ids;
    const sameStyle = next.style_id === current.style_id;
    if (next.mode === 'template') {
      next.shot_ids = patch.shot_ids ?? patch.style_shot_ids ?? (sameStyle ? selected : []);
      next.style_shot_ids = [];
    } else if (next.mode === 'portrait') {
      next.style_shot_ids = patch.style_shot_ids ?? patch.shot_ids ?? (sameStyle ? selected : []);
      next.shot_ids = [];
    }
    next.subject_only = patch.subject_only ?? next.mode === 'template';
  }
  if (next.mode !== 'template') next.subject_only = false;
  if (next.mode === 'template' && next.subject_only) {
    next.notes = subjectOnlyNotes;
    next.mood = '沿用底图色调与光线';
  } else if (current.subject_only) {
    if (patch.notes === undefined && current.notes === subjectOnlyNotes) next.notes = '';
    if (patch.mood === undefined && current.mood === '沿用底图色调与光线') next.mood = '自然柔光';
  }
  return next;
}

/** 仅统计适用于本次方式的选用素材；缺失与超限作为可操作提示。 */
export function describeDraft(
  draft: CreationDraft,
  catalog: Catalog,
  assets: Asset[],
  subjects: Subject[],
) {
  const style = catalog.styles.find((item) => item.id === draft.style_id);
  const capability = catalog.creation_modes.find((item) => item.id === draft.mode);
  const refsActive = draft.mode === 'template' || draft.mode === 'portrait';
  const references = refsActive
    ? assets.filter(
        (asset) =>
          draft.reference_asset_ids.includes(asset.id) &&
          asset.kind === 'reference' &&
          subjects.some(
            (subject) =>
              subject.id === asset.subject_id && subject.authorization_state === 'declared',
          ),
      )
    : [];
  const people = subjects.filter((subject) =>
    references.some((asset) => asset.subject_id === subject.id),
  );
  const shots = style?.shots.filter((shot) => draft.shot_ids.includes(shot.id)) ?? [];
  const styleShots =
    draft.mode === 'portrait'
      ? (style?.shots.filter((shot) => draft.style_shot_ids.includes(shot.id)) ?? [])
      : [];
  const styleAssets =
    draft.mode === 'portrait'
      ? assets.filter(
          (asset) => draft.style_asset_ids?.includes(asset.id) && asset.kind === 'style',
        )
      : [];
  const ratios = outputRatios(draft, style, assets);
  const base =
    draft.mode === 'edit'
      ? assets.find(
          (asset) => asset.id === draft.base_asset_id && ['base', 'photo'].includes(asset.kind),
        )
      : undefined;
  const slots = shots.length
    ? shots[0].subject_slots.filter((slot) =>
        shots.every((shot) => shot.subject_slots.includes(slot)),
      )
    : [];
  const bindings =
    draft.mode === 'template'
      ? people.map((subject) => ({
          subject_id: subject.id,
          position:
            draft.positions[subject.id] ??
            (slots.includes('only')
              ? 'only'
              : subject.subject_key === 'person_a'
                ? 'left'
                : 'right'),
        }))
      : [];
  const inputs =
    (draft.mode === 'template' && shots.length ? 1 : base ? 1 : 0) +
    references.length +
    styleShots.length +
    styleAssets.length;
  const count = draft.mode === 'template' ? shots.length * draft.variants : draft.count;
  const issues = [
    !capability ? '此创作方式当前不可用，请选择已开放方式。' : '',
    !style ? '请选择当前项目可用的套系。' : '',
    (draft.mode === 'template' ? shots : styleShots).some(
      (shot) => !shot.development_only && !shot.rights_approved,
    )
      ? '所选主题图片仅允许展示，尚未开放衍生创作与模型处理用途。'
      : '',
    (draft.mode === 'template' && shots.length !== draft.shot_ids.length) ||
    (draft.mode === 'portrait' && styleShots.length !== draft.style_shot_ids.length)
      ? '部分选中的主题图片已下架或更新，请重新选择。'
      : '',
    draft.mode === 'template' && !shots.length ? '请选择至少一个镜头底图。' : '',
    refsActive && !references.length ? '请添加人物参考，并勾选本次使用的照片。' : '',
    refsActive && references.length !== draft.reference_asset_ids.length
      ? '部分选中的人物参考已失效，请重新选择。'
      : '',
    draft.mode === 'edit' && !base ? '请选择或上传一张要修改的底图。' : '',
    draft.mode === 'portrait' && styleAssets.length !== (draft.style_asset_ids?.length ?? 0)
      ? '部分风格参考已失效，请重新选择。'
      : '',
    draft.mode === 'edit' && !draft.change.trim() ? '请说明想修改什么。' : '',
    draft.mode === 'text' && !draft.notes.trim() ? '请填写想要的画面描述。' : '',
    !draft.mood.trim() ? '请填写画面氛围。' : '',
    draft.notes.length > 1000 || draft.change.length > 1000
      ? '补充要求和修改要求各最多 1000 字。'
      : '',
    !Number.isInteger(count) || count < 1 || count > catalog.max_count
      ? `本次成片需要在 1–${catalog.max_count} 张之间。`
      : '',
    capability && inputs > capability.max_input_images
      ? `每个任务使用 ${inputs} 张图片，超过当前模型 ${capability.max_input_images} 张上限。请调整本次选择。`
      : '',
    capability && references.length > capability.max_reference_images
      ? `当前模型最多使用 ${capability.max_reference_images} 张人物参考。`
      : '',
    capability && styleShots.length + styleAssets.length > capability.max_style_images
      ? `当前模型最多使用 ${capability.max_style_images} 张风格参考。`
      : '',
    capability && people.length > capability.max_subjects
      ? `当前模型最多支持 ${capability.max_subjects} 位参考人物。`
      : '',
    draft.mode === 'template' && bindings.some((binding) => !slots.includes(binding.position))
      ? '人物位置与镜头不匹配，请在提案中重新指定。'
      : '',
    draft.mode === 'template' &&
    new Set(bindings.map((binding) => binding.position)).size !== bindings.length
      ? '不同人物需要对应不同位置。'
      : '',
  ].filter(Boolean);
  return {
    style,
    capability,
    references,
    people,
    shots,
    styleShots,
    styleAssets,
    ratios,
    base,
    slots,
    bindings,
    inputs,
    count,
    issues,
    refsActive,
  };
}

/** 白名单序列化本次输入，服务端会重新编译并验证每个交付项。 */
export function planBody(
  draft: CreationDraft,
  state: ReturnType<typeof describeDraft>,
  revision: number,
): PlanInput {
  if (!state.style || state.issues.length) throw new Error(state.issues[0] ?? '请先选择套系');
  return {
    mode: draft.mode,
    subject_only: draft.mode === 'template' && draft.subject_only,
    style_id: state.style.id,
    style_version: state.style.version,
    aspect_ratio: draft.aspect_ratio,
    count: state.count,
    mood: draft.mood.trim(),
    notes: draft.notes,
    expected_revision: revision,
    reference_asset_ids: state.references.map((asset) => asset.id),
    base_asset_id: state.base?.id ?? null,
    shot_ids: draft.mode === 'template' ? draft.shot_ids : [],
    style_shot_ids: draft.mode === 'portrait' ? draft.style_shot_ids : [],
    style_asset_ids: state.styleAssets.map((asset) => asset.id),
    variants: draft.mode === 'template' ? draft.variants : 1,
    keep: draft.mode === 'edit' ? draft.keep : [],
    change: draft.mode === 'edit' ? draft.change : '',
    subject_bindings: state.bindings,
  };
}

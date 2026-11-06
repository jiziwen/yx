/** 302 模型版本化发布：表单白名单，无凭证字段，不从浏览器传适配器地址。 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  api,
  request,
  expectData,
  type ModelSettings,
  type ModelSettingsInput,
  type ImageModelSettings,
} from '@yingxu/api-client';
import ModelCandidates from './ModelCandidates';
import { modelCandidatesQuery, type ModelCandidate } from '../features/models/candidates';
import { State, Title } from '../shared/ui';

const operations = [
  ['text', '文生图'],
  ['reference', '人物参考生成'],
  ['edit', '图片编辑'],
] as const;
const limits = [
  ['max_input_images', '总输入图片上限'],
  ['max_reference_images', '人物参考图片上限'],
  ['max_style_images', '风格参考图片上限'],
  ['max_subjects', '人物数量上限'],
] as const;

type Draft = Omit<ModelSettingsInput, 'image' | 'vision'> & {
  vision: NonNullable<ModelSettingsInput['vision']>;
  image: ImageModelSettings & {
    operations: NonNullable<ImageModelSettings['operations']>;
    aspect_ratios: NonNullable<ImageModelSettings['aspect_ratios']>;
  };
};

function editable(value: ModelSettings): Draft {
  return {
    expected_revision: value.revision,
    image: {
      ...value.image,
      operations: value.image.operations ?? ['text', 'reference', 'edit'],
      aspect_ratios: value.image.aspect_ratios ?? ['3:4', '4:3', '1:1'],
    },
    llm: { ...value.llm },
    vision: {
      enabled: false,
      model: 'claude-sonnet-5-5',
      max_tokens: 512,
      max_input_images: 2,
      max_dimension: 1024,
      max_bytes: 4000000,
      ...value.vision,
    },
  };
}

export default function ModelsPage() {
  const cache = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState(false);
  const [source, setSource] = useState<ModelCandidate | null>(null);
  const [dirty, setDirty] = useState(false);
  const candidates = useQuery(modelCandidatesQuery);
  const current = useQuery({
    queryKey: ['admin', 'model-settings'],
    queryFn: async () => expectData(await api.GET('/api/v1/admin/model-settings/ai302')),
  });
  const inventory = useQuery({
    queryKey: ['admin', 'ai302-model-list'],
    enabled: false,
    retry: false,
    queryFn: async () => expectData(await api.GET('/api/v1/admin/model-settings/ai302/models')),
  });
  useEffect(() => {
    if (draft || !current.data || !candidates.data) return;
    const latest = candidates.data[0];
    const pending = latest?.status === 'candidate' ? latest : null;
    setSource(pending);
    setDraft(editable({ ...current.data, ...pending?.settings_json }));
  }, [current.data, candidates.data, draft]);
  const publish = useMutation({
    mutationFn: async (body: ModelSettingsInput) =>
      request<ModelCandidate>('/admin/model-candidates', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess(candidate) {
      setSaved(true);
      setDirty(false);
      setSource(candidate);
      cache.setQueryData<ModelCandidate[]>(modelCandidatesQuery.queryKey, (rows) => [
        candidate,
        ...(rows ?? []),
      ]);
      void cache.invalidateQueries({ queryKey: ['model-candidates'] });
      void cache.invalidateQueries({ queryKey: ['admin-catalog'] });
      void cache.invalidateQueries({ queryKey: ['admin', 'audit'] });
    },
  });
  function change(next: Draft) {
    setSaved(false);
    setDirty(true);
    publish.reset();
    setDraft(next);
  }
  function image<K extends keyof Draft['image']>(name: K, value: Draft['image'][K]) {
    if (draft) change({ ...draft, image: { ...draft.image, [name]: value } });
  }
  function loadCandidate(candidate: ModelCandidate) {
    if (!current.data) return;
    setDraft(editable({ ...current.data, ...candidate.settings_json }));
    setSource(candidate);
    setSaved(false);
    setDirty(false);
    publish.reset();
    document.getElementById('model-editor')?.scrollIntoView({ block: 'start' });
  }
  function loadActive(value: ModelSettings) {
    cache.setQueryData(['admin', 'model-settings'], value);
    setDraft(editable(value));
    setSource(null);
    setSaved(false);
    setDirty(false);
    publish.reset();
  }
  async function reload() {
    if (publish.isPending) return;
    const [value, rows] = await Promise.all([current.refetch(), candidates.refetch()]);
    if (value.isSuccess && rows.isSuccess) {
      const latest = rows.data[0];
      const pending = latest?.status === 'candidate' ? latest : null;
      setDraft(editable({ ...value.data, ...pending?.settings_json }));
      setSource(pending);
      setSaved(false);
      setDirty(false);
      publish.reset();
    }
  }
  return (
    <div className="page models-page">
      <Title
        title="302.AI 模型配置"
        description="按创作操作保存模型候选，实测审核后启用；已确认任务保留原模型和档位。"
        onRefresh={() => void reload()}
      />
      {current.isLoading || candidates.isLoading ? (
        <State>加载配置…</State>
      ) : current.error || candidates.error ? (
        <State error={current.error || candidates.error} retry={() => void reload()} />
      ) : (
        draft && (
          <>
            <form
              id="model-editor"
              className="model-settings"
              onSubmit={(event) => {
                event.preventDefault();
                if (!publish.isPending && !saved) publish.mutate(draft);
              }}
            >
              <section className="panel model-settings-banner">
                <div>
                  <strong>当前版本 v{current.data?.revision ?? 0}</strong>
                  <p>
                    图片：{current.data?.image.text_model} · 语言：{current.data?.llm.model}
                  </p>
                  <p>保存候选 → 完成实测 → 审核启用</p>
                </div>
                <span
                  className={'badge ' + (current.data?.credentials_present ? 'active' : 'queued')}
                >
                  {current.data?.credentials_present ? '密钥已配置' : '密钥未配置'}
                </span>
                <button
                  type="button"
                  className="outline"
                  disabled={
                    inventory.isFetching || !current.data?.credentials_present || publish.isPending
                  }
                  onClick={() => void inventory.refetch()}
                >
                  {inventory.isFetching ? '读取中…' : '读取 302 模型列表'}
                </button>
                {inventory.error && <p role="alert">{inventory.error.message}</p>}
                {inventory.data && (
                  <p role="status">
                    已读取 {inventory.data.models.length}{' '}
                    个模型，可在输入框中搜索选择，也可填写新模型 ID。
                  </p>
                )}
                <datalist id="ai302-models">
                  {inventory.data?.models.map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </section>
              <div className="model-editor-status">
                <div>
                  <strong>
                    {dirty
                      ? '有未保存的修改'
                      : source
                        ? '已载入保存的候选配置'
                        : '正在编辑当前生效配置'}
                  </strong>
                  <p>
                    {source
                      ? `候选 ${source.digest.slice(0, 12)} · 审核启用后生效，刷新可继续编辑。`
                      : '修改后保存为候选，再到下方完成启用审核。'}
                  </p>
                </div>
                {source && (
                  <button
                    type="button"
                    className="outline"
                    disabled={publish.isPending}
                    onClick={() => current.data && loadActive(current.data)}
                  >
                    使用当前生效配置
                  </button>
                )}
              </div>
              <fieldset className="panel model-settings-section" disabled={publish.isPending}>
                <legend>图片生成</legend>
                <label className="model-toggle">
                  <input
                    type="checkbox"
                    checked={draft.image.enabled}
                    onChange={(event) => image('enabled', event.target.checked)}
                  />
                  开启真实图片模型
                </label>
                <div className="model-form-grid">
                  <label>
                    模型接口
                    <select
                      value={draft.image.api}
                      onChange={(event) => image('api', event.target.value as 'gpt' | 'unified')}
                    >
                      <option value="gpt">GPT Image · 支持质量档位</option>
                      <option value="unified">302 统一图片接口 · 其他模型</option>
                    </select>
                  </label>
                  <label>
                    图片质量档位
                    <select
                      disabled={draft.image.api !== 'gpt'}
                      value={draft.image.quality}
                      onChange={(event) =>
                        image('quality', event.target.value as ImageModelSettings['quality'])
                      }
                    >
                      <option value="low">low · 开发测试</option>
                      <option value="medium">medium</option>
                      <option value="high">high</option>
                      <option value="auto">auto</option>
                    </select>
                  </label>
                  <label>
                    文生图模型
                    <input
                      list="ai302-models"
                      required
                      value={draft.image.text_model}
                      onChange={(event) => image('text_model', event.target.value)}
                    />
                  </label>
                  <label>
                    人物参考模型
                    <input
                      list="ai302-models"
                      required
                      value={draft.image.reference_model}
                      onChange={(event) => image('reference_model', event.target.value)}
                    />
                  </label>
                  <label>
                    图片编辑模型
                    <input
                      list="ai302-models"
                      required
                      value={draft.image.edit_model}
                      onChange={(event) => image('edit_model', event.target.value)}
                    />
                  </label>
                </div>
                <p className="model-help">
                  low
                  适合开发草稿。切换模型时，请按实际支持情况调整操作、人数和图数；模型列表可见不代表写真效果已通过验收。
                </p>
                <div className="model-choice-row" role="group" aria-label="开放操作">
                  {operations.map(([operation, label]) => (
                    <label key={operation}>
                      <input
                        type="checkbox"
                        checked={draft.image.operations.includes(operation)}
                        onChange={(event) =>
                          image(
                            'operations',
                            event.target.checked
                              ? [...draft.image.operations, operation]
                              : draft.image.operations.filter((value) => value !== operation),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </div>
                <div className="model-form-grid">
                  {limits.map(([name, label]) => (
                    <label key={name}>
                      {label}
                      <input
                        type="number"
                        min={0}
                        max={name === 'max_subjects' ? 2 : 20}
                        required
                        value={draft.image[name]}
                        onChange={(event) => image(name, Number(event.target.value))}
                      />
                    </label>
                  ))}
                </div>
                <p className="model-hint">
                  尺寸不限，按用户选择或底图实际尺寸发送，由模型接口处理。
                </p>
              </fieldset>
              <fieldset className="panel model-settings-section" disabled={publish.isPending}>
                <legend>大语言模型</legend>
                <label className="model-toggle">
                  <input
                    type="checkbox"
                    checked={draft.llm.enabled}
                    onChange={(event) => {
                      change({ ...draft, llm: { ...draft.llm, enabled: event.target.checked } });
                    }}
                  />
                  启用语言模型网关
                </label>
                <div className="model-form-grid">
                  <label>
                    大语言模型 ID
                    <input
                      list="ai302-models"
                      required
                      value={draft.llm.model}
                      onChange={(event) => {
                        change({ ...draft, llm: { ...draft.llm, model: event.target.value } });
                      }}
                    />
                  </label>
                  <label>
                    单次最大输出 token
                    <input
                      type="number"
                      min={32}
                      max={4096}
                      required
                      value={draft.llm.max_tokens}
                      onChange={(event) => {
                        change({
                          ...draft,
                          llm: { ...draft.llm, max_tokens: Number(event.target.value) },
                        });
                      }}
                    />
                  </label>
                </div>
                <p className="model-help">
                  Sonnet 5.5 的模型 ID 为
                  claude-sonnet-5-5。正式工作室会使用这里发布的语言模型理解需求、追问和整理草稿；生成图片仍需用户确认。
                </p>
              </fieldset>
              <fieldset className="panel model-settings-section" disabled={publish.isPending}>
                <legend>视觉分析 · 独立配置</legend>
                <label className="model-toggle">
                  <input
                    type="checkbox"
                    checked={draft.vision?.enabled ?? false}
                    onChange={(event) =>
                      change({
                        ...draft,
                        vision: { ...draft.vision, enabled: event.target.checked },
                      })
                    }
                  />
                  启用视觉分析候选
                </label>
                <div className="model-form-grid">
                  <label className="model-field-wide">
                    视觉模型 ID
                    <input
                      list="ai302-models"
                      required
                      value={draft.vision?.model ?? ''}
                      onChange={(event) =>
                        change({ ...draft, vision: { ...draft.vision, model: event.target.value } })
                      }
                    />
                  </label>
                  {(['max_input_images', 'max_dimension', 'max_bytes', 'max_tokens'] as const).map(
                    (key) => (
                      <label key={key}>
                        {
                          {
                            max_input_images: '单次图片上限',
                            max_dimension: '最长边像素',
                            max_bytes: '请求图片总字节上限',
                            max_tokens: '输出 token 上限',
                          }[key]
                        }
                        <input
                          type="number"
                          required
                          min={
                            {
                              max_input_images: 1,
                              max_dimension: 256,
                              max_bytes: 100000,
                              max_tokens: 32,
                            }[key]
                          }
                          max={
                            {
                              max_input_images: 4,
                              max_dimension: 2048,
                              max_bytes: 8000000,
                              max_tokens: 4096,
                            }[key]
                          }
                          value={
                            draft.vision?.[key] ??
                            {
                              max_input_images: 2,
                              max_dimension: 1024,
                              max_bytes: 4000000,
                              max_tokens: 512,
                            }[key]
                          }
                          onChange={(event) =>
                            change({
                              ...draft,
                              vision: { ...draft.vision, [key]: Number(event.target.value) },
                            })
                          }
                        />
                      </label>
                    ),
                  )}
                </div>
                <p className="model-help">
                  视觉能力需单独实测与审核，通过后启用。图片字节上限的单位为 B。
                </p>
              </fieldset>
              <section className="panel model-settings-footer">
                <div className="model-save-copy">
                  <strong>{saved ? '候选已保存' : dirty ? '修改尚未保存' : '保存与启用'}</strong>
                  <p>
                    保存只创建候选，不切换当前模型。审核启用后 API 与 Worker
                    才读取新版本；已确认任务继续使用原配置。
                  </p>
                </div>
                {publish.error && (
                  <p className="model-feedback error" role="alert">
                    保存失败：{publish.error.message}
                  </p>
                )}
                {saved && (
                  <p className="model-feedback success" role="status">
                    候选已保存，刷新后可继续编辑。<a href="#model-candidates">前往审核启用 →</a>
                  </p>
                )}
                <button
                  className="primary"
                  disabled={publish.isPending || saved || !draft.image.operations.length}
                >
                  {publish.isPending ? '保存候选中…' : saved ? '已保存候选' : '保存为候选新版本'}
                </button>
              </section>
            </form>
            <ModelCandidates
              revision={current.data?.revision ?? 0}
              onLoad={loadCandidate}
              onActivated={loadActive}
              saving={publish.isPending}
            />
          </>
        )
      )}
    </div>
  );
}

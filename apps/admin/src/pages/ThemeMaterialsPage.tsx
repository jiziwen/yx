/** 主题套系与素材即时发布；用途和来源逐图填写，无需改配置重启。 */
import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  api,
  ApiError,
  expectData,
  newKey,
  type User,
  type ThemeCatalog,
  type ThemeShot,
  type ThemeStyle,
  type ThemeSave,
} from '@yingxu/api-client';
import { State, Title } from '../shared/ui';

/** 直接列出本次编辑仍缺的开放条件，保存目录与开放创作分别反馈。 */
function missingUses(shot: ThemeShot): string[] {
  return [
    !shot.source_record.trim() ? '来源与使用依据' : '',
    !shot.display ? '网站展示' : '',
    !shot.derivative ? '衍生创作' : '',
    !shot.model_processing ? '发送给模型处理' : '',
    !shot.enabled ? '镜头可用' : '',
  ].filter(Boolean);
}

/** 数量按保存返回的实际配置计算，不把版本更新等同于所有图片已开放。 */
function availableShots(style: ThemeStyle): number {
  return style.enabled ? style.shots.filter((shot) => !missingUses(shot).length).length : 0;
}

/** 断线后恢复同一保存键；不保存密码、Cookie或图片正文。 */
function restore(key: string): ThemeSave | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return value &&
      typeof value.request_key === 'string' &&
      Number.isInteger(value.expected_revision) &&
      typeof value.style?.id === 'string' &&
      Array.isArray(value.style.shots)
      ? value
      : null;
  } catch {
    return null;
  }
}

/** 服务端只接受编辑字段；预览、图片摘要和确认人不由客户端声明。 */
function saveBody(style: ThemeStyle): ThemeSave['style'] {
  return {
    id: style.id,
    name: style.name,
    kind: style.kind,
    theme_id: style.theme_id,
    mood: style.mood,
    description: style.description,
    enabled: style.enabled,
    shots: style.shots.map((shot) => ({
      id: shot.id,
      name: shot.name,
      material_id: shot.material_id,
      position: shot.position,
      subject_slots: shot.subject_slots,
      enabled: shot.enabled,
      source_record: shot.source_record,
      display: shot.display,
      derivative: shot.derivative,
      model_processing: shot.model_processing,
    })),
  };
}

/** 恢复保存请求的预览仅通过管理API，不把本地对象键拼到浏览器。 */
function restoreStyle(pending: ThemeSave): ThemeStyle {
  return {
    ...pending.style,
    version: '',
    shots: pending.style.shots.map((shot) => ({
      ...shot,
      checksum: '',
      reviewed_by: '',
      development_only: false,
      rights_approved: false,
      image: shot.material_id
        ? `/api/v1/admin/theme-materials/images/${shot.material_id}/content`
        : `/api/v1/admin/theme-materials/styles/${pending.style.id}/shots/${shot.id}/content`,
    })),
  };
}

export default function ThemeMaterialsPage() {
  const cache = useQueryClient();
  const actor = cache.getQueryData<User>(['admin-me']);
  const storageKey = `yx:pending-theme-save:${actor?.id}`;
  const [pending, setPending] = useState<ThemeSave | null>(() => restore(storageKey));
  const [editor, setEditor] = useState<ThemeStyle | null>(() =>
    pending ? restoreStyle(pending) : null,
  );
  const [revision, setRevision] = useState(pending?.expected_revision ?? 0);
  const [isNew, setIsNew] = useState(false);
  const [message, setMessage] = useState('');
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historySelection, setHistorySelection] = useState<{ id: string; styleId: string } | null>(
    null,
  );
  const [files, setFiles] = useState<Record<string, { file: File; key: string }>>({});
  const inFlight = useRef(false);
  const catalog = useQuery({
    queryKey: ['theme-catalog'],
    queryFn: () => api.GET('/api/v1/admin/theme-materials').then(expectData),
    refetchOnWindowFocus: 'always',
  });
  const history = useQuery({
    queryKey: ['theme-releases', historyOffset],
    queryFn: () =>
      api
        .GET('/api/v1/admin/theme-materials/releases', {
          params: { query: { offset: historyOffset } },
        })
        .then(expectData),
  });
  const historyDetail = useQuery({
    queryKey: ['theme-release-detail', historySelection?.id],
    enabled: !!historySelection,
    queryFn: () =>
      api
        .GET('/api/v1/admin/theme-materials/releases/{release_id}', {
          params: { path: { release_id: historySelection!.id } },
        })
        .then(expectData),
  });
  const historicalStyle = historyDetail.data?.styles.find(
    (style) => style.id === historySelection?.styleId,
  );
  useEffect(() => {
    if (catalog.data && !editor && !pending) {
      setEditor(catalog.data.styles[0] ?? null);
      setRevision(catalog.data.revision);
    }
  }, [catalog.data, editor, pending]);
  const refresh = () => {
    void catalog.refetch();
    void cache.invalidateQueries({ queryKey: ['theme-releases'] });
    void cache.invalidateQueries({ queryKey: ['admin-catalog'] });
  };
  const updateShot = (id: string, patch: Partial<ThemeShot>) =>
    setEditor((old) =>
      old
        ? {
            ...old,
            shots: old.shots.map((shot) => (shot.id === id ? { ...shot, ...patch } : shot)),
          }
        : old,
    );
  const upload = useMutation({
    mutationFn: ({ file, key }: { id: string; file: File; key: string }) =>
      api
        .POST('/api/v1/admin/theme-materials/images', {
          body: { request_key: key, file: file.name },
          bodySerializer: () => {
            const form = new FormData();
            form.set('request_key', key);
            form.set('file', file);
            return form;
          },
        })
        .then(expectData),
    onSuccess: (image, variables) => {
      updateShot(variables.id, {
        material_id: image.id,
        image: image.image,
        checksum: image.checksum,
        source_record: '',
        display: false,
        derivative: false,
        model_processing: false,
        development_only: false,
        rights_approved: false,
      });
      setFiles((old) => {
        const copy = { ...old };
        delete copy[variables.id];
        return copy;
      });
      setMessage('图片已上传，请填写这张图片的来源与用途，保存后生效。');
    },
  });
  const save = useMutation({
    mutationFn: (body: ThemeSave) =>
      api.POST('/api/v1/admin/theme-materials', { body }).then(expectData),
    onSuccess: (value, body) => {
      sessionStorage.removeItem(storageKey);
      setPending(null);
      setIsNew(false);
      cache.setQueryData<ThemeCatalog>(['theme-catalog'], value);
      const published = value.styles.find((style) => style.id === body.style.id) ?? null;
      setEditor(published);
      setRevision(value.revision);
      setHistoryOffset(0);
      const ready = published ? availableShots(published) : 0;
      setMessage(
        `已保存并生效 · 目录 v${value.revision}；${ready} 张可用于创作，${(published?.shots.length ?? 0) - ready} 张未开放创作。${ready ? '工作室会自动同步。' : '请按镜头下方提示补齐来源和允许用途后保存。'}`,
      );
      refresh();
    },
    onError: (error) => {
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.status !== 408
      ) {
        sessionStorage.removeItem(storageKey);
        setPending(null);
      }
      refresh();
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const locked = !!pending || save.isPending || upload.isPending;
  const choose = (id: string) => {
    setEditor(catalog.data?.styles.find((style) => style.id === id) ?? null);
    setRevision(catalog.data?.revision ?? 0);
    setIsNew(false);
    setFiles({});
    setMessage('');
    save.reset();
    upload.reset();
  };
  const addShot = () => {
    const shot: ThemeShot = {
      id: `shot_${newKey().replaceAll('-', '').slice(0, 12)}`,
      name: '新镜头',
      material_id: null,
      position: '50% 35%',
      subject_slots: [
        editor?.kind === 'wedding' ? 'left' : 'only',
        ...(editor?.kind === 'wedding' ? ['right' as const] : []),
      ],
      enabled: true,
      source_record: '',
      display: false,
      derivative: false,
      model_processing: false,
      image: '',
      checksum: '',
      reviewed_by: '',
      development_only: false,
      rights_approved: false,
    };
    setEditor((old) => (old ? { ...old, shots: [...old.shots, shot] } : old));
  };
  if (catalog.isLoading) return <State>正在加载主题素材…</State>;
  if (catalog.error && !catalog.data)
    return <State error={catalog.error} retry={() => catalog.refetch()} />;
  return (
    <div className="page model-settings theme-materials">
      <Title
        title="主题素材"
        description="上传图片、记录来源及允许用途，保存后直接发布到灵感库和工作室。"
        onRefresh={refresh}
      />
      <section className="panel grant-panel">
        <div className="table-toolbar">
          <label>
            编辑套系{' '}
            <select
              aria-label="编辑主题套系"
              disabled={locked}
              value={isNew ? '' : (editor?.id ?? '')}
              onChange={(event) => choose(event.target.value)}
            >
              <option value="">请选择套系</option>
              {catalog.data?.styles.map((style) => (
                <option key={style.id} value={style.id}>
                  {style.name} · {style.id}
                  {style.enabled ? '' : '（已停用）'}
                </option>
              ))}
            </select>
          </label>
          <button
            className="outline"
            disabled={locked}
            onClick={() => {
              setIsNew(true);
              setFiles({});
              setMessage('');
              save.reset();
              upload.reset();
              setRevision(catalog.data?.revision ?? 0);
              setEditor({
                id: '',
                name: '',
                kind: 'portrait',
                theme_id: 'portrait',
                mood: '柔光',
                description: '',
                enabled: true,
                shots: [],
                version: '',
              });
            }}
          >
            新增套系
          </button>
        </div>
        <p className="subtle">
          当前目录 v{catalog.data?.revision ?? 0} ·
          每个套系最多12个镜头。保存会以当前管理员记录本次来源与用途确认。
        </p>
        {editor && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (inFlight.current || upload.isPending) return;
              const body = pending ?? {
                request_key: newKey(),
                expected_revision: revision,
                style: saveBody(editor),
              };
              try {
                sessionStorage.setItem(storageKey, JSON.stringify(body));
              } catch {
                setMessage('无法保存请求，请允许当前页面使用会话存储后重试。');
                return;
              }
              setPending(body);
              setMessage('');
              inFlight.current = true;
              save.mutate(body);
            }}
          >
            <div className="grant-notice" role="note" aria-label="创作开放检查">
              <strong>
                本次配置：{availableShots(editor)} / {editor.shots.length} 张可用于创作
              </strong>
              <p>
                {editor.enabled
                  ? '各镜头的缺项列在图片下方；补齐来源和三项允许用途后保存，即可开放真实创作。'
                  : '套系当前已停用，启用并保存后才会出现在用户目录。'}
              </p>
            </div>
            <fieldset className="grant-fields" disabled={locked}>
              <div className="model-form-grid">
                <label>
                  套系名称
                  <input
                    aria-label="套系名称"
                    value={editor.name}
                    maxLength={100}
                    required
                    onChange={(event) => setEditor({ ...editor, name: event.target.value })}
                  />
                </label>
                <label>
                  套系标识
                  <input
                    aria-label="套系标识"
                    value={editor.id}
                    readOnly={!isNew}
                    pattern="[a-z0-9_-]{1,80}"
                    required
                    onChange={(event) => setEditor({ ...editor, id: event.target.value })}
                    placeholder="例如 moonlight_portrait"
                  />
                </label>
                <label>
                  项目类型
                  <select
                    aria-label="套系项目类型"
                    disabled={!isNew}
                    value={editor.kind}
                    onChange={(event) =>
                      setEditor({ ...editor, kind: event.target.value as ThemeStyle['kind'] })
                    }
                  >
                    <option value="portrait">个人写真</option>
                    <option value="wedding">双人婚纱</option>
                  </select>
                </label>
                <label>
                  画面氛围
                  <input
                    aria-label="套系氛围"
                    required
                    maxLength={120}
                    value={editor.mood}
                    onChange={(event) => setEditor({ ...editor, mood: event.target.value })}
                  />
                </label>
                <label>
                  外观主题标识
                  <input
                    aria-label="外观主题标识"
                    value={editor.theme_id}
                    required
                    pattern="[a-z0-9_-]{1,80}"
                    onChange={(event) => setEditor({ ...editor, theme_id: event.target.value })}
                  />
                </label>
                <label>
                  套系说明
                  <textarea
                    aria-label="套系说明"
                    maxLength={500}
                    value={editor.description}
                    onChange={(event) => setEditor({ ...editor, description: event.target.value })}
                  />
                </label>
              </div>
              <label className="theme-check">
                <input
                  type="checkbox"
                  checked={editor.enabled}
                  onChange={(event) => setEditor({ ...editor, enabled: event.target.checked })}
                />
                套系可用（关闭后从用户目录下架）
              </label>
              {editor.shots.map((shot, index) => (
                <section
                  className="theme-shot-editor"
                  key={shot.id}
                  aria-label={`镜头 ${index + 1}`}
                >
                  <div className="theme-shot-preview">
                    {shot.image ? (
                      <img src={shot.image} alt={`镜头预览 ${index + 1}`} />
                    ) : (
                      <p>请上传镜头图片</p>
                    )}
                    <span>
                      {shot.development_only
                        ? '既有内测样片'
                        : shot.rights_approved
                          ? '已开放创作'
                          : '用途待配置 / 仅展示'}
                    </span>
                  </div>
                  <div>
                    <h3>
                      镜头 {index + 1} <small>{shot.id}</small>
                    </h3>
                    <div className="model-form-grid">
                      <label>
                        镜头名称
                        <input
                          aria-label={`镜头 ${index + 1} 名称`}
                          value={shot.name}
                          required
                          maxLength={100}
                          onChange={(event) => updateShot(shot.id, { name: event.target.value })}
                        />
                      </label>
                      <label>
                        更换图片
                        <input
                          aria-label={`镜头 ${index + 1} 图片`}
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file)
                              setFiles((old) => ({ ...old, [shot.id]: { file, key: newKey() } }));
                          }}
                        />
                      </label>
                    </div>
                    {files[shot.id] && (
                      <button
                        type="button"
                        className="outline"
                        onClick={() => upload.mutate({ id: shot.id, ...files[shot.id] })}
                      >
                        上传镜头 {index + 1} 图片
                      </button>
                    )}
                    <div className="model-form-grid">
                      <label>
                        来源与使用依据
                        <textarea
                          aria-label={`镜头 ${index + 1} 来源`}
                          placeholder="填写创作/购买/授权记录及允许用途的依据"
                          value={shot.source_record}
                          maxLength={300}
                          required={shot.display || shot.derivative || shot.model_processing}
                          onChange={(event) =>
                            updateShot(shot.id, { source_record: event.target.value })
                          }
                        />
                      </label>
                      <label>
                        人物位置
                        <select
                          aria-label={`镜头 ${index + 1} 人物位置`}
                          value={shot.subject_slots.join(',')}
                          onChange={(event) =>
                            updateShot(shot.id, {
                              subject_slots:
                                event.target.value === 'only' ? ['only'] : ['left', 'right'],
                            })
                          }
                        >
                          <option value="only">单人主体</option>
                          <option value="left,right">双人（左 / 右）</option>
                        </select>
                      </label>
                    </div>
                    <div className="theme-uses">
                      {(
                        [
                          ['display', '网站展示'],
                          ['derivative', '衍生创作'],
                          ['model_processing', '发送给模型处理'],
                        ] as const
                      ).map(([key, label]) => (
                        <label key={key}>
                          <input
                            type="checkbox"
                            aria-label={`镜头 ${index + 1} ${label}`}
                            checked={shot[key]}
                            onChange={(event) =>
                              updateShot(shot.id, { [key]: event.target.checked })
                            }
                          />
                          {label}
                        </label>
                      ))}
                      <label>
                        <input
                          type="checkbox"
                          aria-label={`镜头 ${index + 1} 可用`}
                          checked={shot.enabled}
                          onChange={(event) =>
                            updateShot(shot.id, { enabled: event.target.checked })
                          }
                        />
                        镜头可用
                      </label>
                    </div>
                    <p className="subtle">
                      仅展示可用于浏览；用于真实出图需要三项用途均允许。替换图片后需重新填写来源及用途。
                    </p>
                    {!!missingUses(shot).length && (
                      <p
                        className="grant-notice"
                        role="note"
                        aria-label={`镜头 ${index + 1} 开放缺项`}
                      >
                        保存后仍不能用于创作，缺少：{missingUses(shot).join('、')}。
                      </p>
                    )}
                    {shot.reviewed_by && <p className="subtle">上次确认人：{shot.reviewed_by}</p>}
                    <div className="theme-shot-actions">
                      <button
                        type="button"
                        disabled={index === 0}
                        onClick={() =>
                          setEditor({
                            ...editor,
                            shots: editor.shots.map((item, i, rows) =>
                              i === index - 1 ? shot : i === index ? rows[index - 1] : item,
                            ),
                          })
                        }
                      >
                        上移
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditor({
                            ...editor,
                            shots: editor.shots.filter((item) => item.id !== shot.id),
                          });
                          setFiles((old) => {
                            const copy = { ...old };
                            delete copy[shot.id];
                            return copy;
                          });
                        }}
                      >
                        移除镜头
                      </button>
                    </div>
                  </div>
                </section>
              ))}
              <button
                type="button"
                className="outline"
                disabled={editor.shots.length >= 12}
                onClick={addShot}
              >
                添加镜头
              </button>
            </fieldset>
            {Object.keys(files).length > 0 && <p>有图片尚未上传，请先点击对应的上传按钮。</p>}
            {upload.isPending && <p role="status">图片上传中…</p>}
            {upload.error && (
              <p role="alert" className="error">
                上传失败：{upload.error.message}，可保留所选文件重试。
              </p>
            )}
            {save.error && (
              <p role="alert" className="error">
                保存未确认：{save.error.message}
              </p>
            )}
            {pending && !save.isPending && (
              <p className="grant-notice">
                保存结果待核对，重试本次保存不会重复发布；刷新后也会保留同一请求。
              </p>
            )}
            {catalog.data?.revision !== revision && (
              <p className="grant-notice">
                目录已有更新，当前编辑仍保留；请核对后重新载入生效版本。
              </p>
            )}
            {message && <p role="status">{message}</p>}
            <div className="theme-shot-actions">
              <button
                className="primary"
                type="submit"
                disabled={save.isPending || upload.isPending || Object.keys(files).length > 0}
              >
                {save.isPending ? '保存中…' : pending ? '重试本次保存' : '保存并生效'}
              </button>
              <button
                className="outline"
                type="button"
                disabled={locked}
                onClick={() => choose(editor.id)}
              >
                重新载入生效版本
              </button>
            </div>
          </form>
        )}
      </section>
      <section className="panel grant-panel">
        <h2>发布记录</h2>
        {history.isLoading ? (
          <State>正在加载发布记录…</State>
        ) : history.error ? (
          <State error={history.error} retry={() => history.refetch()} />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>目录版本</th>
                  <th>套系</th>
                  <th>保存人</th>
                  <th>时间</th>
                  <th>发布记录 ID</th>
                  <th>历史内容</th>
                </tr>
              </thead>
              <tbody>
                {history.data?.map((item) => (
                  <tr key={item.id}>
                    <td>v{item.revision}</td>
                    <td>{item.style_id}</td>
                    <td>{item.actor_name}</td>
                    <td>{new Date(item.created_at).toLocaleString('zh-CN')}</td>
                    <td>{item.id}</td>
                    <td>
                      <button
                        className="outline"
                        onClick={() => setHistorySelection({ id: item.id, styleId: item.style_id })}
                      >
                        查看本版
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!history.data?.length && <State>暂无后台发布记录，当前使用初始目录。</State>}
          </div>
        )}
        <div className="grant-pager">
          <button
            className="outline"
            disabled={!historyOffset}
            onClick={() => setHistoryOffset(Math.max(0, historyOffset - 30))}
          >
            上一页
          </button>
          <button
            className="outline"
            disabled={(history.data?.length ?? 0) < 30}
            onClick={() => setHistoryOffset(historyOffset + 30)}
          >
            下一页
          </button>
        </div>
        {historySelection && (
          <section aria-label="历史版本内容">
            <div className="theme-shot-actions">
              <h3>历史版本 v{historyDetail.data?.revision ?? '…'} · 只读</h3>
              <button onClick={() => setHistorySelection(null)}>收起历史内容</button>
            </div>
            {historyDetail.isLoading ? (
              <State>正在加载历史内容…</State>
            ) : historyDetail.error ? (
              <State error={historyDetail.error} retry={() => historyDetail.refetch()} />
            ) : (
              historicalStyle && (
                <>
                  <p>
                    {historicalStyle.name} · {historicalStyle.mood}
                  </p>
                  {historicalStyle.shots.map((shot) => (
                    <article className="theme-shot-editor" key={shot.id}>
                      <div className="theme-shot-preview">
                        <img src={shot.image} alt={'历史镜头 ' + shot.name} />
                      </div>
                      <div>
                        <h3>{shot.name}</h3>
                        <p>来源：{shot.source_record || '未记录'}</p>
                        <p>
                          展示：{shot.display ? '允许' : '未允许'} · 衍生创作：
                          {shot.derivative ? '允许' : '未允许'} · 模型处理：
                          {shot.model_processing ? '允许' : '未允许'}
                        </p>
                        <p>确认人：{shot.reviewed_by || '未记录'}</p>
                        <small className="grant-id">图片摘要：{shot.checksum}</small>
                      </div>
                    </article>
                  ))}
                </>
              )
            )}
          </section>
        )}
      </section>
    </div>
  );
}

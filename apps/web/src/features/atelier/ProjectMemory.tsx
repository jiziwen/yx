/** 用户确认的项目记忆；模型建议与长期保存有独立、可审阅的确认入口。 */
import { useEffect, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useMutation } from '@tanstack/react-query';
import { Bookmark, Check, Pencil } from 'lucide-react';
import { api, expectData, type ProjectMemory } from '@yingxu/api-client';
import { Modal } from '../../shared/ui';
import { useTheme } from '../../themes/ThemeProvider';

type MemoryBody = {
  expected_revision: number;
  expected_privacy_epoch: number;
  requirements: string[];
  source_run_id?: string;
  fields?: Record<string, string>;
};
/** 只有显式用户操作调用 PUT；Agent 的只读工具没有此函数或端点。 */
async function saveMemory(projectId: string, body: MemoryBody) {
  return expectData(
    await api.PUT('/api/v1/web/projects/{project_id}/memory', {
      params: { path: { project_id: projectId } },
      body,
    }),
  );
}

/** 项目要求可查看、编辑、清空，多窗口变更不会覆盖当前编辑内容。 */
export function ProjectMemoryPanel({
  projectId,
  memory,
  readonly,
  onSaved,
}: {
  projectId: string;
  memory: ProjectMemory;
  readonly: boolean;
  onSaved: (value: ProjectMemory) => void;
}) {
  const { theme } = useTheme();
  const [editor, setEditor] = useState<{
    text: string;
    revision: number;
    epoch: number;
    fields: Record<string, string>;
  } | null>(null);
  const mutation = useMutation({
    mutationFn: (body: MemoryBody) => saveMemory(projectId, body),
    onSuccess: (value) => {
      setEditor(null);
      onSaved(value);
    },
  });
  useEffect(() => {
    setEditor(null);
    mutation.reset();
  }, [memory.privacy_epoch]);
  if (!memory.enabled) return null;
  const items = editor
    ? [
        ...new Set(
          editor.text
            .split('\n')
            .map((item) => item.trim())
            .filter(Boolean),
        ),
      ]
    : [];
  const stale =
    !!editor && (editor.revision !== memory.revision || editor.epoch !== memory.privacy_epoch);
  const invalid =
    items.length > memory.max_items ||
    items.some((item) => item.length > 160) ||
    (memory.field_definitions ?? []).some(
      (field) => (editor?.fields[field.key]?.length ?? 0) > field.max_length,
    );
  const open = () => {
    mutation.reset();
    setEditor({
      text: memory.requirements.join('\n'),
      revision: memory.revision,
      epoch: memory.privacy_epoch,
      fields: { ...(memory.fields ?? {}) },
    });
  };
  return (
    <div className="at-project-memory">
      <div>
        <span>
          <Bookmark size={12} />
          项目记忆 · {memory.requirements.length} 条
        </span>
        <button disabled={readonly} onClick={open} aria-label="管理项目记忆">
          <Pencil size={11} />
          管理
        </button>
      </div>
      {(memory.field_definitions ?? []).length > 0 && (
        <details className="at-brief-card">
          <summary>创作需求卡 · {Object.keys(memory.fields ?? {}).length} 项已确认</summary>
          <dl aria-label="已确认创作需求">
            {(memory.field_definitions ?? []).map((field) => (
              <div key={field.key}>
                <dt>{field.label}</dt>
                <dd>{(memory.fields ?? {})[field.key] || '待一起确定'}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {memory.requirements.length ? (
        <ul>
          {memory.requirements.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p>确认过的要求，会陪着之后每一轮创作。</p>
      )}
      {editor &&
        createPortal(
          <div className="at-memory-dialog" style={theme.tokens as CSSProperties}>
            <Modal
              title="让 Lumi 记住的要求"
              onClose={() => !mutation.isPending && setEditor(null)}
            >
              <p>
                每行一条，最多 {memory.max_items} 条，每条 160
                字。仅用于后续对话，不会修改已保存提案或启动图片生成。
              </p>
              {(memory.field_definitions ?? []).length > 0 && (
                <fieldset className="at-brief-editor">
                  <legend>创作需求卡</legend>
                  {(memory.field_definitions ?? []).map((field) => (
                    <label key={field.key} className="at-memory-editor">
                      {field.label}
                      <textarea
                        rows={2}
                        aria-label={`需求卡${field.label}`}
                        maxLength={field.max_length}
                        value={editor.fields[field.key] ?? ''}
                        disabled={mutation.isPending}
                        onChange={(event) =>
                          setEditor({
                            ...editor,
                            fields: { ...editor.fields, [field.key]: event.target.value },
                          })
                        }
                      />
                    </label>
                  ))}
                </fieldset>
              )}
              <label className="at-memory-editor">
                项目长期要求
                <textarea
                  aria-label="项目长期要求"
                  rows={7}
                  value={editor.text}
                  maxLength={2200}
                  disabled={mutation.isPending}
                  onChange={(event) => setEditor({ ...editor, text: event.target.value })}
                  placeholder={'例如：不要头纱\n保留自然的五官与肤色'}
                />
              </label>
              {stale && (
                <p role="alert">
                  项目记忆已在其他页面更新，请载入最新内容后再编辑。
                  <button onClick={open}>载入最新记忆</button>
                </p>
              )}
              {invalid && <p role="alert">请控制条数和单条长度后再确认。</p>}
              {mutation.error && <p role="alert">{mutation.error.message}</p>}
              <div className="at-memory-actions">
                <button
                  disabled={mutation.isPending || readonly}
                  onClick={() => setEditor({ ...editor, text: '', fields: {} })}
                >
                  清空内容
                </button>
                <button
                  disabled={mutation.isPending || readonly || stale || invalid}
                  onClick={() =>
                    mutation.mutate({
                      expected_revision: editor.revision,
                      expected_privacy_epoch: editor.epoch,
                      requirements: items,
                      fields: editor.fields,
                    })
                  }
                >
                  <Check size={13} />
                  {mutation.isPending ? '正在保存' : '确认保存记忆'}
                </button>
              </div>
            </Modal>
          </div>,
          document.body,
        )}
    </div>
  );
}

/** 模型提出的要求必须先展示，用户点击确认后才合并到当前项目记忆。 */
export function MemorySuggestion({
  projectId,
  memory,
  runId,
  sourceRevision,
  suggestions,
  readonly,
  onSaved,
}: {
  projectId: string;
  memory: ProjectMemory;
  runId: string;
  sourceRevision: number | undefined;
  suggestions: string[];
  readonly: boolean;
  onSaved: (value: ProjectMemory) => void;
}) {
  const mutation = useMutation({
    mutationFn: (body: MemoryBody) => saveMemory(projectId, body),
    onSuccess: onSaved,
  });
  const requirements = [...new Set([...memory.requirements, ...suggestions])];
  const remembered = suggestions.every((item) => memory.requirements.includes(item));
  const stale = sourceRevision !== memory.revision;
  if (!memory.enabled || !suggestions.length) return null;
  return (
    <div className="at-chat-suggestion at-memory-suggestion">
      <small>
        <Bookmark size={12} />
        想替你记住这些要求
      </small>
      <ul>
        {suggestions.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p>
        {remembered
          ? '已保存在这个项目的长期记忆中。'
          : stale
            ? '项目记忆已有新版本，请重新整理或在上方管理。'
            : '只有你确认后，才会用于之后的创作对话。'}
      </p>
      <button
        disabled={
          readonly ||
          mutation.isPending ||
          remembered ||
          stale ||
          requirements.length > memory.max_items
        }
        onClick={() =>
          mutation.mutate({
            expected_revision: memory.revision,
            expected_privacy_epoch: memory.privacy_epoch,
            requirements,
            source_run_id: runId,
          })
        }
      >
        <Check size={12} />
        {remembered ? '已记住' : '确认记住'}
      </button>
      {requirements.length > memory.max_items && <p>要求已达到上限，请先到项目记忆中整理。</p>}
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
    </div>
  );
}

/** 结构化补丁先展示原值/建议，用户确认后完整替换当前字段，与文字记忆共享版本。 */
export function BriefSuggestion({
  projectId,
  memory,
  runId,
  sourceRevision,
  patch,
  readonly,
  onSaved,
}: {
  projectId: string;
  memory: ProjectMemory;
  runId: string;
  sourceRevision: number | undefined;
  patch: Record<string, string>;
  readonly: boolean;
  onSaved: (value: ProjectMemory) => void;
}) {
  const mutation = useMutation({
    mutationFn: (body: MemoryBody) => saveMemory(projectId, body),
    onSuccess: onSaved,
  });
  if (!memory.enabled || !Object.keys(patch).length) return null;
  const stale = sourceRevision !== memory.revision;
  const invalid = Object.entries(patch).some(([key, value]) => {
    const field = (memory.field_definitions ?? []).find((item) => item.key === key);
    return !field || value.length > field.max_length;
  });
  const fields = Object.fromEntries(
    Object.entries({ ...(memory.fields ?? {}), ...patch }).filter(([, value]) => value.trim()),
  );
  const unchanged = Object.entries(patch).every(
    ([key, value]) => ((memory.fields ?? {})[key] ?? '') === value,
  );
  return (
    <div className="at-chat-suggestion at-brief-suggestion">
      <small>为你整理的创作需求卡</small>
      <dl>
        {Object.entries(patch).map(([key, value]) => (
          <div key={key}>
            <dt>
              {(memory.field_definitions ?? []).find((field) => field.key === key)?.label ??
                '已停用字段'}
            </dt>
            <dd>
              <span>原要求：{(memory.fields ?? {})[key] || '未确认'}</span>
              <span>建议：{value || '清除此项'}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p>
        {unchanged
          ? '这些要求已确认。'
          : stale || invalid
            ? '需求或配置已更新，请重新整理或到上方管理。'
            : '确认后用于后续创作，不修改当前草稿，也不生成图片。'}
      </p>
      <button
        disabled={readonly || mutation.isPending || stale || invalid || unchanged}
        onClick={() =>
          mutation.mutate({
            expected_revision: memory.revision,
            expected_privacy_epoch: memory.privacy_epoch,
            requirements: memory.requirements,
            fields,
            source_run_id: runId,
          })
        }
      >
        <Check size={12} />
        {unchanged ? '已确认需求' : '确认保存需求卡'}
      </button>
      {mutation.error && <p role="alert">{mutation.error.message}</p>}
    </div>
  );
}

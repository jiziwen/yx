/** 私有草稿自动保存；冲突保留本地编辑，冻结方案绑定服务端版本。 */
import { useEffect, useRef, useState } from 'react';
import { ApiError, request } from '@yingxu/api-client';
import type { CreationDraft } from './creationDraft';
import { sameDraft } from './StudioGuide';

type Stored = { revision: number; privacy_epoch: number; draft: CreationDraft | null };
export default function useStudioDraft(
  projectId: string,
  epoch: number,
  initial: CreationDraft,
  readonly: boolean,
) {
  const [draft, setDraft] = useState(initial);
  const [stored, setStored] = useState<Stored | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);
  const generation = useRef(0);
  const url = `/web/projects/${projectId}/studio-draft`;
  const reload = async () => {
    const current = ++generation.current;
    setSaving(true);
    try {
      const value = await request<Stored>(url);
      if (current !== generation.current) return;
      setStored(value);
      setDraft(
        value.draft
          ? { ...initial, ...value.draft, style_asset_ids: value.draft.style_asset_ids ?? [] }
          : initial,
      );
      setError(null);
    } catch (cause) {
      if (current === generation.current) setError(cause as Error);
    } finally {
      if (current === generation.current) setSaving(false);
    }
  };
  useEffect(() => {
    void reload();
    return () => {
      generation.current += 1;
    };
  }, [projectId, epoch]);
  const synced = !!stored && stored.privacy_epoch === epoch && sameDraft(draft, stored.draft);
  useEffect(() => {
    if (!stored || synced || readonly || saving || error) return;
    const current = generation.current;
    const timer = setTimeout(async () => {
      setSaving(true);
      try {
        const value = await request<Stored>(url, {
          method: 'PUT',
          body: JSON.stringify({
            expected_revision: stored.revision,
            expected_privacy_epoch: epoch,
            draft,
          }),
        });
        if (current === generation.current) setStored(value);
      } catch (cause) {
        if (current === generation.current) setError(cause as Error);
      } finally {
        if (current === generation.current) setSaving(false);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [draft, stored, synced, readonly, saving, error, epoch, url]);
  useEffect(() => {
    if (!stored || saving || error) return;
    let alive = true;
    const check = async () => {
      try {
        const remote = await request<Stored>(url);
        if (alive && remote.revision > stored.revision)
          setError(new Error('另一窗口更新了草稿。当前编辑仍保留，请选择载入最新草稿。'));
      } catch {
        /* 保存和确认入口仍会验证身份；短暂离线不覆盖用户编辑。 */
      }
    };
    const timer = setInterval(() => void check(), 5000);
    window.addEventListener('focus', check);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener('focus', check);
    };
  }, [stored, saving, error, url]);
  useEffect(() => {
    if (error instanceof ApiError && error.status === 422) setError(null);
  }, [draft]);
  return { draft, setDraft, stored, synced, saving, error, reload, retry: () => setError(null) };
}

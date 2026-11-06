/** 人物参考图与声明管理；照片只通过私有 API 读取。 */
import { useEffect, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  request,
  assetUrl,
  type Subject,
  type Asset,
  type ProjectMemory,
} from '@yingxu/api-client';
import { Plus, Upload, ShieldCheck } from 'lucide-react';
import { useApp } from '../../app/context';
/** 人物槽一次声明授权，撤销后不可用旧素材重新执行。 */
export default function SubjectPanel({
  projectId,
  kind,
  subjects,
  assets,
  refresh,
  readonly = false,
  onUploaded,
}: {
  projectId: string;
  kind: string;
  subjects: Subject[];
  assets: Asset[];
  refresh: () => void;
  readonly?: boolean;
  onUploaded?: (asset: Asset) => void;
}) {
  const { notify } = useApp();
  const [slot, setSlot] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [consent, setConsent] = useState(false);
  const [keep, setKeep] = useState<string[]>([]);
  const [generic, setGeneric] = useState(false);
  const memory = useQuery({
    queryKey: ['deletion-memory', projectId, subjects, assets.length],
    queryFn: () => request<ProjectMemory>(`/web/projects/${projectId}/memory`),
  });
  useEffect(() => {
    setKeep([]);
    setGeneric(false);
  }, [memory.data?.revision]);
  const retention = () =>
    keep.length
      ? JSON.stringify({
          expected_memory_revision: memory.data?.revision,
          requirements: keep,
          generic_text_only: generic,
        })
      : undefined;
  const remove = useMutation({
    mutationFn: (id: string) =>
      request(`/web/assets/${id}`, { method: 'DELETE', body: retention() }),
    onSuccess: () => {
      refresh();
      void memory.refetch();
    },
    onError: (error) => notify(error.message),
  });

  const create = useMutation({
    mutationFn: () =>
      request(`/web/projects/${projectId}/subjects`, {
        method: 'POST',
        body: JSON.stringify({ subject_key: slot, display_name: name, declared: consent }),
      }),
    onSuccess: () => {
      refresh();
      setSlot(null);
      setName('');
      setConsent(false);
    },
    onError: (error) => notify(error.message),
  });
  const upload = useMutation({
    mutationFn: ({ subjectId, file }: { subjectId: string; file: File }) => {
      const form = new FormData();
      form.set('subject_id', subjectId);
      form.set('file', file);
      return request<Asset>(`/web/projects/${projectId}/uploads`, { method: 'POST', body: form });
    },
    onSuccess: (asset) => {
      onUploaded?.(asset);
      refresh();
    },
    onError: (error) => notify(error.message),
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      request(`/web/subjects/${id}/revoke`, { method: 'POST', body: retention() }),
    onSuccess: () => {
      refresh();
      notify('授权已撤销，相关照片已停止访问，后台将继续清理。');
    },
    onError: (error) => notify(error.message),
  });
  return (
    <section className="subject-panel">
      <div className="section-label">
        <span>01 / YOUR PEOPLE</span>
        <ShieldCheck size={15} />
      </div>
      <h2>故事里的主角</h2>
      <p className="muted">清晰、自然的照片，是认识你的开始。</p>
      <p className="cx-fineprint">
        取消选用只调整本轮输入；真正删除或撤销授权会清理相关原图、派生作品、分析及旧聊天。
      </p>
      {!!memory.data?.requirements.length && (
        <details>
          <summary>删除或撤销时，选择保留通用文字偏好（可选）</summary>
          {memory.data.requirements.map((value) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={keep.includes(value)}
                onChange={(event) =>
                  setKeep((current) =>
                    event.target.checked
                      ? [...current, value]
                      : current.filter((item) => item !== value),
                  )
                }
              />
              {value}
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={generic}
              onChange={(event) => setGeneric(event.target.checked)}
            />
            这些是脱离照片仍成立的通用文字偏好，不含人物识别或图像观察。
          </label>
        </details>
      )}
      {(kind === 'wedding' ? ['person_a', 'person_b'] : ['person_a']).map((key, index) => {
        const subject = subjects.find((s) => s.subject_key === key);
        return (
          <div className="subject-slot" key={key}>
            {subject ? (
              <>
                <div className="subject-heading">
                  <span className="person-avatar">{index === 0 ? 'A' : 'B'}</span>
                  <div>
                    <strong>{subject.display_name}</strong>
                    <small>
                      {subject.authorization_state === 'declared' ? '已声明使用授权' : '授权已撤销'}
                    </small>
                  </div>
                </div>
                {subject.authorization_state === 'declared' && (
                  <>
                    <div className="reference-grid">
                      {assets
                        .filter(
                          (asset) => asset.subject_id === subject.id && asset.kind === 'reference',
                        )
                        .map((asset) => (
                          <figure key={asset.id}>
                            <img src={assetUrl(asset.id)} alt={subject.display_name + '参考照片'} />
                            <button
                              type="button"
                              disabled={readonly || remove.isPending || (!!keep.length && !generic)}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    '真正删除这张参考照及派生作品，并清理相关分析和旧聊天？',
                                  )
                                )
                                  remove.mutate(asset.id);
                              }}
                            >
                              真正删除
                            </button>
                          </figure>
                        ))}
                    </div>
                    <label
                      className={
                        'upload-target ' + (upload.isPending || readonly ? 'disabled' : '')
                      }
                    >
                      <Upload size={18} />
                      <span>{upload.isPending ? '正在上传与校验…' : '上传参考照片'}</span>
                      <small>JPG / PNG / WebP · 最多 10 MB</small>
                      <input
                        aria-label={'上传' + subject.display_name + '参考照'}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        disabled={upload.isPending || readonly}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) upload.mutate({ subjectId: subject.id, file });
                          event.target.value = '';
                        }}
                      />
                    </label>
                    <button
                      className="text-button muted"
                      disabled={revoke.isPending || readonly || (!!keep.length && !generic)}
                      onClick={() => {
                        if (
                          window.confirm(
                            '撤销后会停止使用并清理该人物的参考照片与派生作品，是否继续？',
                          )
                        )
                          revoke.mutate(subject.id);
                      }}
                    >
                      撤销人物使用授权
                    </button>
                  </>
                )}
              </>
            ) : slot === key ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  create.mutate();
                }}
              >
                <label>
                  人物称呼
                  <input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={index === 0 ? '例如：我' : '例如：另一位主角'}
                    required
                    maxLength={80}
                  />
                </label>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(event) => setConsent(event.target.checked)}
                    required
                  />
                  <span>我已获得本人同意，有权上传和使用其照片进行创作。</span>
                </label>
                <button className="button" disabled={!consent || create.isPending}>
                  确认并添加
                </button>
              </form>
            ) : (
              <button className="add-person" disabled={readonly} onClick={() => setSlot(key)}>
                <Plus size={20} />
                添加{index === 0 ? '第一位' : '第二位'}主角
              </button>
            )}
          </div>
        );
      })}
      <p className="privacy-note">
        <ShieldCheck size={14} />
        参考照片私密保存，仅用于你确认的创作。
      </p>
    </section>
  );
}

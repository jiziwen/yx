/** 知识原文导入、索引状态、真实分块预览及显式版本发布/下架。 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  api,
  expectData,
  type KnowledgeDocument,
  type KnowledgeImport,
  type KnowledgeVersion,
} from '@yingxu/api-client';
import { Title, State } from '../shared/ui';
const statuses: Record<string, string> = {
  queued: '等待索引',
  indexing: '正在索引',
  ready: '可预览发布',
  failed: '索引未完成',
};
export default function KnowledgePage() {
  const cache = useQueryClient();
  const [id, setId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [category, setCategory] = useState<KnowledgeImport['category']>('product');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [validUntil, setValidUntil] = useState('');
  const docs = useQuery({
    queryKey: ['knowledge-documents'],
    queryFn: () => api.GET('/api/v1/admin/knowledge/documents').then(expectData),
    refetchInterval: 5000,
  });
  const doc = docs.data?.find((item) => item.id === id);
  const versions = useQuery({
    queryKey: ['knowledge-versions', id],
    enabled: !!id,
    queryFn: () =>
      api
        .GET('/api/v1/admin/knowledge/documents/{document_id}/versions', {
          params: { path: { document_id: id! } },
        })
        .then(expectData),
    refetchInterval: 2000,
  });
  const preview = useQuery({
    queryKey: ['knowledge-preview', selected],
    enabled: !!selected,
    queryFn: () =>
      api
        .GET('/api/v1/admin/knowledge/versions/{version_id}/preview', {
          params: { path: { version_id: selected! } },
        })
        .then(expectData),
  });
  const refresh = async () => {
    await cache.invalidateQueries({ queryKey: ['knowledge-documents'] });
    await cache.invalidateQueries({ queryKey: ['knowledge-versions', id] });
  };
  const create = useMutation({
    mutationFn: () => api.POST('/api/v1/admin/knowledge/documents').then(expectData),
    onSuccess: (value) => {
      setId(value.id);
      setSelected(null);
      cache.setQueryData<KnowledgeDocument[]>(['knowledge-documents'], (old) => [
        value,
        ...(old ?? []),
      ]);
    },
  });
  const requestKey = useState(() => crypto.randomUUID())[0];
  const [importKey, setImportKey] = useState(requestKey);
  const load = useMutation({
    mutationFn: async () => {
      const body: KnowledgeImport = {
        expected_revision: doc!.revision,
        request_key: importKey,
        title,
        summary,
        category,
        text: file ? 'file' : text,
        valid_until: validUntil ? new Date(validUntil).toISOString() : null,
      };
      if (!file)
        return expectData(
          await api.POST('/api/v1/admin/knowledge/documents/{document_id}/versions', {
            params: { path: { document_id: id! } },
            body,
          }),
        );
      const metadata = JSON.stringify(body);
      return expectData(
        await api.POST('/api/v1/admin/knowledge/documents/{document_id}/files', {
          params: { path: { document_id: id! } },
          body: { file: file.name, metadata },
          bodySerializer: () => {
            const form = new FormData();
            form.append('file', file);
            form.append('metadata', metadata);
            return form;
          },
        }),
      );
    },
    onSuccess: (value) => {
      setSelected(value.id);
      setImportKey(crypto.randomUUID());
      setText('');
      setFile(null);
      void refresh();
    },
    onError: () => void refresh(),
  });
  const publish = useMutation({
    mutationFn: async ({ version, remove }: { version: KnowledgeVersion; remove: boolean }) => {
      const options = {
        params: { path: { document_id: id! } },
        body: { expected_revision: doc!.revision, version_id: version.id },
      };
      return remove
        ? expectData(
            await api.POST('/api/v1/admin/knowledge/documents/{document_id}/unpublish', options),
          )
        : expectData(
            await api.POST('/api/v1/admin/knowledge/documents/{document_id}/publish', options),
          );
    },
    onSuccess: () => void refresh(),
    onError: () => void refresh(),
  });
  const busy = load.isPending || publish.isPending;
  return (
    <>
      <Title
        title="知识库"
        description="导入面向客户的文档，索引并预览后发布。价格、次数与任务状态仍由业务服务提供。"
        onRefresh={() => void refresh()}
      />
      <div className="m2-admin-layout">
        <section className="panel">
          <h2>知识文档</h2>
          <button onClick={() => create.mutate()} disabled={create.isPending}>
            新建知识文档
          </button>
          {docs.isLoading && <State>正在读取文档…</State>}
          {docs.error && <State error={docs.error} retry={() => void docs.refetch()} />}
          <ul className="m2-admin-list">
            {docs.data?.map((item, index) => (
              <li key={item.id}>
                <button
                  aria-pressed={id === item.id}
                  onClick={() => {
                    setId(item.id);
                    setSelected(null);
                    setImportKey(crypto.randomUUID());
                  }}
                >
                  文档 {docs.data!.length - index} · r{item.revision}
                  <small>{item.published_version_id ? '已发布' : '未发布'}</small>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <div>
          {doc ? (
            <>
              <form
                className="panel m2-admin-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  load.mutate();
                }}
              >
                <h2>导入新版本</h2>
                <p>
                  当前 r{doc.revision}。旧发布版本在新版本准备期间继续可用。文档会交给配置的
                  embedding 模型索引。
                </p>
                <label>
                  知识标题
                  <input
                    required
                    maxLength={120}
                    value={title}
                    onChange={(e) => {
                      setTitle(e.target.value);
                      setImportKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <label>
                  内容摘要
                  <input
                    maxLength={300}
                    value={summary}
                    onChange={(e) => {
                      setSummary(e.target.value);
                      setImportKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <label>
                  知识分类
                  <select
                    value={category}
                    onChange={(e) => {
                      setCategory(e.target.value as KnowledgeImport['category']);
                      setImportKey(crypto.randomUUID());
                    }}
                  >
                    <option value="product">产品使用</option>
                    <option value="photography">摄影准备</option>
                    <option value="wedding">婚礼指南</option>
                  </select>
                </label>
                <label>
                  正文
                  <textarea
                    aria-label="知识正文"
                    rows={8}
                    maxLength={60000}
                    value={text}
                    disabled={!!file}
                    onChange={(e) => {
                      setText(e.target.value);
                      setImportKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <label>
                  或上传 MD / TXT / 有文本层 PDF
                  <input
                    type="file"
                    accept=".md,.txt,.pdf"
                    onChange={(e) => {
                      setFile(e.target.files?.[0] ?? null);
                      setImportKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <label>
                  有效期结束（可留空）
                  <input
                    type="datetime-local"
                    value={validUntil}
                    onChange={(e) => {
                      setValidUntil(e.target.value);
                      setImportKey(crypto.randomUUID());
                    }}
                  />
                </label>
                <button disabled={busy || !title.trim() || (!file && !text.trim())}>
                  导入并建立索引
                </button>
              </form>
              <section className="panel">
                <h2>版本与发布</h2>
                {versions.error && (
                  <State error={versions.error} retry={() => void versions.refetch()} />
                )}
                <div className="m2-admin-versions">
                  {versions.data?.map((version) => (
                    <article key={version.id}>
                      <strong>
                        v{version.version_no} · {version.title}
                      </strong>
                      <span>
                        {statuses[version.status] ?? version.status}
                        {doc.published_version_id === version.id ? ' · 当前发布' : ''}
                        {version.embedding_spec.development_sample ? ' · 开发索引样例' : ''}
                      </span>
                      {version.error_code && (
                        <p role="status">
                          {version.error_code}。原发布不受影响，可重新导入新版本。
                        </p>
                      )}
                      <div>
                        <button
                          className="outline"
                          onClick={() => {
                            setSelected(version.id);
                            void cache.invalidateQueries({
                              queryKey: ['knowledge-preview', version.id],
                            });
                          }}
                        >
                          预览正文
                        </button>
                        {doc.published_version_id === version.id ? (
                          <button
                            disabled={busy}
                            onClick={() => publish.mutate({ version, remove: true })}
                          >
                            下架此版本
                          </button>
                        ) : (
                          <button
                            disabled={
                              busy ||
                              version.status !== 'ready' ||
                              !!version.revoked_at ||
                              selected !== version.id ||
                              !preview.data?.length
                            }
                            onClick={() => publish.mutate({ version, remove: false })}
                          >
                            审核并发布
                          </button>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
              {selected && (
                <section className="panel">
                  <h2>发布前正文预览</h2>
                  <p>引用依据以下实际片段。请核对正确性后点击对应版本“审核并发布”。</p>
                  {preview.error && (
                    <State error={preview.error} retry={() => void preview.refetch()} />
                  )}
                  <div className="m2-admin-preview">
                    {preview.data?.length ? (
                      preview.data.map((chunk) => (
                        <article key={chunk.ordinal}>
                          <small>{chunk.locator}</small>
                          <p>{chunk.text}</p>
                        </article>
                      ))
                    ) : (
                      <p>索引尚未生成片段，完成后点击“预览正文”。</p>
                    )}
                  </div>
                </section>
              )}
            </>
          ) : (
            <section className="panel">
              <h2>让回答有据可查</h2>
              <p>
                先新建或选择文档，再导入面向客户的公开知识。未发布、索引失败、过期和下架的版本都不会被客户检索。
              </p>
            </section>
          )}
        </div>
      </div>
      {(load.error ?? publish.error ?? create.error) && (
        <p role="alert">{(load.error ?? publish.error ?? create.error)?.message}</p>
      )}
    </>
  );
}

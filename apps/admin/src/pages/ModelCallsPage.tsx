/** 图片提交与轮询按任务合并展示；实际入出参在弹框中按需读取。 */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { State, Title } from '../shared/ui';

const kinds: Record<string, string> = {
  llm: '语言模型',
  image: '图片模型',
  vision: '视觉模型',
  embedding: '向量模型',
};
const operations: Record<string, string> = {
  draft: '整理草稿',
  complete: '完整回复',
  stream_complete: '流式回复',
  generate: '生成图片',
  submit: '提交图片',
  lookup: '查询图片结果',
  embed: '生成向量',
};
const statuses: Record<string, string> = {
  running: '等待最终记录',
  succeeded: '已返回',
  failed: '调用异常',
};
function time(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}
function json(value: unknown, empty = '暂无响应（可能仍在调用中，或未收到上游响应）') {
  return value == null ? empty : JSON.stringify(value, null, 2);
}
function prompt(request: unknown): string | null {
  if (!request || typeof request !== 'object') return null;
  const record = request as Record<string, unknown>;
  for (const key of ['prompt', 'messages', 'input', 'texts']) {
    const value = record[key];
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return json(value);
  }
  for (const key of ['json', 'data', 'request']) {
    const value = prompt(record[key]);
    if (value) return value;
  }
  return null;
}

function CallDialog({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    const previousFocus = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    element.showModal();
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="model-call-dialog"
      aria-modal="true"
      aria-labelledby="model-call-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="model-call-dialog-content">
        <div className="job-detail-head model-call-dialog-head">
          <h2 id="model-call-dialog-title">模型调用详情</h2>
          <button onClick={onClose}>关闭详情</button>
        </div>
        <div className="model-call-dialog-body">{children}</div>
      </div>
    </dialog>
  );
}

export default function ModelCallsPage() {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [callsPage, setCallsPage] = useState(1);
  const [entryId, setEntryId] = useState<string | null>(null);
  const records = useQuery({
    queryKey: ['admin', 'model-calls', page],
    queryFn: async () =>
      expectData(await api.GET('/api/v1/admin/model-calls', { params: { query: { page } } })),
  });
  const detail = useQuery({
    queryKey: ['admin', 'model-call', selected, callsPage],
    enabled: !!selected,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[2] === selected ? previous : undefined,
    queryFn: async () =>
      expectData(
        await api.GET('/api/v1/admin/model-calls/{call_id}', {
          params: { path: { call_id: selected! }, query: { calls_page: callsPage } },
        }),
      ),
  });
  const entry = useQuery({
    queryKey: ['admin', 'model-call-payload', entryId],
    enabled: !!selected && !!entryId,
    queryFn: async () =>
      expectData(
        await api.GET('/api/v1/admin/model-calls/{call_id}/payload', {
          params: { path: { call_id: entryId! } },
        }),
      ),
  });
  const data = records.data;
  const current = detail.data;
  const shown = entryId ? entry.data : current;
  const inputPrompt = prompt(current?.request);
  function openDetail(id: string) {
    setCallsPage(1);
    setEntryId(null);
    setSelected(id);
  }
  return (
    <div className="page">
      <Title
        title="模型调用"
        description="查看各个模型的实际入参、出参和提示词，每页 20 条。"
        onRefresh={() => {
          void records.refetch();
          if (selected) void detail.refetch();
          if (entryId) void entry.refetch();
        }}
      />
      <p className="model-calls-note">
        同一图片任务的提交与结果查询合并展示，展开详情可查看每次请求。密钥已脱敏，图片二进制省略，超长内容会标记裁剪。
      </p>
      <section className="panel" aria-label="模型调用列表">
        <div className="table-toolbar">
          <span>共 {data?.total ?? '—'} 条 · 每页 20 条</span>
        </div>
        {records.isLoading ? (
          <State>加载中…</State>
        ) : records.error ? (
          <State error={records.error} retry={() => records.refetch()} />
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>调用时间</th>
                    <th>类型 / 模型</th>
                    <th>操作</th>
                    <th>最近状态</th>
                    <th>累计耗时</th>
                    <th>HTTP / 错误</th>
                    <th>详情</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.items.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {time(row.created_at)}
                        <small className="model-call-id">{row.id}</small>
                      </td>
                      <td>
                        {kinds[row.kind] ?? row.kind}
                        <strong className="model-call-model">{row.model}</strong>
                        {row.development_sample && <span className="badge">开发插件</span>}
                      </td>
                      <td>
                        {row.kind === 'image' && row.call_count > 1
                          ? '图片生成'
                          : (operations[row.operation] ?? row.operation)}
                        {row.call_count > 1 && (
                          <small className="model-call-id">
                            合并 {row.call_count} 次请求 · 查询 {row.lookup_count} 次
                          </small>
                        )}
                      </td>
                      <td>
                        <span className={'badge ' + row.status}>
                          {statuses[row.status] ?? row.status}
                        </span>
                        {row.result_unknown && (
                          <small className="model-call-id">远端结果未知</small>
                        )}
                      </td>
                      <td>
                        {row.latency_ms == null ? '—' : `${(row.latency_ms / 1000).toFixed(2)} 秒`}
                      </td>
                      <td>
                        {row.http_status ?? '—'}
                        <small className="model-call-id">{row.error_code}</small>
                      </td>
                      <td>
                        <button
                          className="record-action"
                          aria-haspopup="dialog"
                          onClick={() => openDetail(row.id)}
                        >
                          查看入参 / 出参
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!data?.items.length && (
                <State>暂无调用记录。发送一条工作室聊天或确认生成后，可在这里查看。</State>
              )}
            </div>
            <nav className="model-calls-pagination" aria-label="模型调用分页">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
                上一页
              </button>
              <span>
                第 {page} / {Math.max(1, data?.total_pages ?? 1)} 页
              </span>
              <button disabled={page >= (data?.total_pages ?? 0)} onClick={() => setPage(page + 1)}>
                下一页
              </button>
            </nav>
          </>
        )}
      </section>
      {selected && (
        <CallDialog onClose={() => setSelected(null)}>
          {detail.isLoading ? (
            <State>读取详情中…</State>
          ) : detail.error ? (
            <State error={detail.error} retry={() => detail.refetch()} />
          ) : (
            current && (
              <>
                <p className="job-detail-id">{current.id}</p>
                <dl className="job-facts">
                  <div>
                    <dt>供应商插件</dt>
                    <dd>{current.provider_id}</dd>
                  </div>
                  <div>
                    <dt>模型</dt>
                    <dd>{current.model}</dd>
                  </div>
                  <div>
                    <dt>项目 ID</dt>
                    <dd>{current.project_id ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>用户 ID</dt>
                    <dd>{current.owner_user_id ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>Agent Run ID</dt>
                    <dd>{current.run_id ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>图片任务 ID</dt>
                    <dd>{current.job_id ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>最近状态</dt>
                    <dd>
                      {statuses[current.status] ?? current.status}
                      {current.result_unknown ? ' · 远端结果未知' : ''}
                    </dd>
                  </div>
                  <div>
                    <dt>请求记录</dt>
                    <dd>
                      共 {current.call_count} 次 · 查询 {current.lookup_count} 次
                    </dd>
                  </div>
                </dl>
                {current.scrubbed ? (
                  <p role="status">项目授权已变化或账户已删除，入参和出参正文已清除。</p>
                ) : (
                  <section className="model-call-prompt">
                    <h3>{current.kind === 'embedding' ? '输入文本' : '提示词 / 消息'}</h3>
                    <pre aria-label="调用提示词">
                      {inputPrompt ??
                        (current.operation === 'lookup'
                          ? '历史记录中没有找到原始提交入参，仅保留结果查询参数。'
                          : '当前记录未包含提示词或消息，请查看下方实际入参。')}
                    </pre>
                  </section>
                )}
                {current.status === 'running' && (
                  <p role="status">
                    尚未收到最终记录。进程中断也可能保留此状态，请结合任务状态核对。
                  </p>
                )}
                <div className="model-call-payload-head">
                  <h3>{entryId ? '本次请求入出参' : '调用入参与出参'}</h3>
                  {entryId && <button onClick={() => setEntryId(null)}>返回调用汇总</button>}
                </div>
                {!entryId && current.call_count > 1 && (
                  <p className="model-calls-note">
                    入参来自最初提交，出参来自最近一次操作（
                    {operations[current.latest_operation] ?? current.latest_operation} ·{' '}
                    {time(current.latest_at)}）。每次操作的实际参数可在下方查看。
                  </p>
                )}
                {entryId && entry.isLoading ? (
                  <State>读取本次请求中…</State>
                ) : entryId && entry.error ? (
                  <State error={entry.error} retry={() => entry.refetch()} />
                ) : (
                  shown && (
                    <>
                      {entryId && (
                        <p className="model-calls-note">
                          {operations[shown.operation] ?? shown.operation} ·{' '}
                          {time(shown.created_at)} · {statuses[shown.status] ?? shown.status} · HTTP{' '}
                          {shown.http_status ?? '—'} · {shown.error_code ?? '无错误'}
                          <br />
                          {shown.id}
                        </p>
                      )}
                      <div className="model-call-payloads">
                        <section>
                          <h3>实际入参</h3>
                          <pre aria-label="调用入参">{json(shown.request, '暂无入参记录')}</pre>
                        </section>
                        <section>
                          <h3>实际出参</h3>
                          <pre aria-label="调用出参">{json(shown.response)}</pre>
                        </section>
                      </div>
                    </>
                  )
                )}
                {current.call_count > 1 && (
                  <details className="model-call-history">
                    <summary>每次请求明细（{current.call_count} 次）</summary>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>时间</th>
                            <th>操作</th>
                            <th>状态</th>
                            <th>HTTP / 错误</th>
                            <th>入出参</th>
                          </tr>
                        </thead>
                        <tbody>
                          {current.calls.map((call) => (
                            <tr key={call.id} aria-selected={entryId === call.id}>
                              <td>{time(call.created_at)}</td>
                              <td>{operations[call.operation] ?? call.operation}</td>
                              <td>{statuses[call.status] ?? call.status}</td>
                              <td>
                                {call.http_status ?? '—'}
                                <small className="model-call-id">{call.error_code}</small>
                              </td>
                              <td>
                                <button
                                  className="record-action"
                                  onClick={() => setEntryId(call.id)}
                                >
                                  查看本次入出参
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <nav className="model-calls-pagination" aria-label="请求明细分页">
                      <button
                        disabled={detail.isFetching || callsPage <= 1}
                        onClick={() => setCallsPage(callsPage - 1)}
                      >
                        上一页请求
                      </button>
                      <span>
                        第 {current.calls_page} / {Math.max(1, current.calls_total_pages)} 页
                      </span>
                      <button
                        disabled={detail.isFetching || callsPage >= current.calls_total_pages}
                        onClick={() => setCallsPage(callsPage + 1)}
                      >
                        下一页请求
                      </button>
                    </nav>
                  </details>
                )}
                <p className="model-calls-note">
                  流式回复展示合并后的内容与用量。已返回表示本次操作正常返回，图片最终状态请结合出参或「生成任务」核对。历史未记录的正文无法补回。
                </p>
              </>
            )
          )}
        </CallDialog>
      )}
    </div>
  );
}

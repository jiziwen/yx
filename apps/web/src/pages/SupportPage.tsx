/** 梦幻主题下的独立客服：只读答疑、可核对引用、用户请求人工与原生回复恢复。 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  api,
  expectData,
  ApiError,
  type SupportConversation,
  type SupportMessageInput,
} from '@yingxu/api-client';
import { RequireUser, useApp } from '../app/context';
import { Heading, Status } from '../shared/ui';
import Citations from '../features/conversations/Citations';
import RunSteps from '../features/conversations/RunSteps';
import ToolObservations from '../features/atelier/ToolObservations';
import useConversationStream from '../features/atelier/useConversationStream';

export default function SupportPage() {
  return (
    <RequireUser>
      <SupportChat />
    </RequireUser>
  );
}
function SupportChat() {
  const { user } = useApp();
  const [params] = useSearchParams();
  const projectId = params.get('project') || null;
  const [input, setInput] = useState('');
  const [revoked, setRevoked] = useState(false);
  const [older, setOlder] = useState<SupportConversation['messages']>([]);
  const pending = useRef<SupportMessageInput | null>(null);
  const log = useRef<HTMLDivElement>(null);
  const historyAnchor = useRef<{ height: number; top: number } | null>(null);
  const cache = useQueryClient();
  const open = useQuery({
    queryKey: ['support-open', user?.id, projectId],
    queryFn: () =>
      api.POST('/api/v1/web/conversations', { body: { project_id: projectId } }).then(expectData),
    retry: false,
  });
  const id = open.data?.id;
  const key = ['support-chat', user?.id, id];
  const query = useQuery({
    queryKey: key,
    enabled: !!id,
    queryFn: () =>
      api
        .GET('/api/v1/web/conversations/{conversation_id}', {
          params: { path: { conversation_id: id! } },
        })
        .then(expectData),
    refetchInterval: 2000,
    retry: (count, error) =>
      !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && count < 2,
  });
  const view = revoked ? undefined : (query.data ?? open.data);
  const epoch = view?.privacy_epoch ?? 0;
  const current = useRef({ id, epoch });
  current.current = { id, epoch };
  const refresh = () => cache.invalidateQueries({ queryKey: key });
  const connection = useConversationStream({
    projectId: id ?? '',
    conversationId: id,
    privacyEpoch: epoch,
    enabled: !!id && !query.error && !revoked,
    onSync: refresh,
    onReset: () => {
      setOlder([]);
      pending.current = null;
      setInput('');
      void refresh();
    },
    onRevoked: () => {
      setRevoked(true);
      setOlder([]);
      pending.current = null;
      cache.removeQueries({ queryKey: key });
      cache.invalidateQueries({ queryKey: ['me'] });
    },
  });
  useEffect(() => {
    setOlder([]);
    setInput('');
    pending.current = null;
  }, [id, epoch]);
  useEffect(() => setRevoked(false), [id]);
  const active = view?.runs.find((run) => ['queued', 'running'].includes(run.status));
  const preview = active ? (connection.previews[active.id]?.preview ?? active.reply_preview) : null;
  const messages = [
    ...new Map(
      [...older, ...(view?.messages ?? [])].map((message) => [message.id, message]),
    ).values(),
  ].sort((a, b) => a.seq - b.seq);
  useEffect(() => {
    if (!older.length)
      log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'instant' });
  }, [messages.at(-1)?.id, preview?.text, older.length]);
  const send = useMutation({
    mutationFn: (body: SupportMessageInput) =>
      api
        .POST('/api/v1/web/conversations/{conversation_id}/messages', {
          params: { path: { conversation_id: id! } },
          body,
        })
        .then(expectData),
    onSuccess: (value) => {
      if (value.id !== current.current.id || value.privacy_epoch !== current.current.epoch) return;
      pending.current = null;
      setInput('');
      cache.setQueryData(key, value);
    },
    onError: () => void refresh(),
  });
  const handoff = useMutation({
    mutationFn: () =>
      api
        .POST(
          view!.handoff_status === 'bot'
            ? '/api/v1/web/conversations/{conversation_id}/handoff'
            : '/api/v1/web/conversations/{conversation_id}/handoff/withdraw',
          {
            params: { path: { conversation_id: id! } },
            body: { expected_revision: view!.revision },
          },
        )
        .then(expectData),
    onSuccess: (value) => {
      if (value.id !== current.current.id || value.privacy_epoch !== current.current.epoch) return;
      cache.setQueryData(key, value);
    },
    onError: () => void refresh(),
  });
  const [cursor, setCursor] = useState<string | null | undefined>(undefined);
  useEffect(() => setCursor(undefined), [id, epoch]);
  useLayoutEffect(() => {
    if (historyAnchor.current && log.current) {
      log.current.scrollTop =
        historyAnchor.current.top + log.current.scrollHeight - historyAnchor.current.height;
      historyAnchor.current = null;
    }
  }, [older.length]);
  const history = useMutation({
    onMutate: () => {
      if (log.current)
        historyAnchor.current = { height: log.current.scrollHeight, top: log.current.scrollTop };
    },
    mutationFn: () =>
      api
        .GET('/api/v1/web/conversations/{conversation_id}', {
          params: {
            path: { conversation_id: id! },
            query: { cursor: cursor ?? view?.older_cursor ?? undefined },
          },
        })
        .then(expectData),
    onError: () => {
      historyAnchor.current = null;
    },
    onSuccess: (page) => {
      if (page.id === current.current.id && page.privacy_epoch === current.current.epoch) {
        setOlder((old) => [...new Map([...page.messages, ...old].map((m) => [m.id, m])).values()]);
        setCursor(page.older_cursor);
      }
    },
  });
  const submit = () => {
    if (!view || !input.trim()) return;
    const text = input.trim();
    if (!pending.current || pending.current.text !== text)
      pending.current = {
        client_message_id: crypto.randomUUID(),
        text,
        expected_revision: view.revision,
        expected_privacy_epoch: epoch,
      };
    pending.current = {
      ...pending.current,
      expected_revision: view.revision,
      expected_privacy_epoch: epoch,
    };
    send.mutate(pending.current);
  };
  const errors = send.error ?? handoff.error ?? history.error;
  return (
    <div className="page-content m2-support-page">
      <Heading
        eyebrow="A LITTLE HELP, ALWAYS HERE"
        title="有些问题，我们一起想清楚。"
        description="Lumi 帮你查规则和创作进度；需要时，可以请人工客服一起处理。"
      />
      <Status
        loading={open.isLoading}
        error={open.error ?? query.error}
        retry={() => {
          void open.refetch();
          void query.refetch();
        }}
      >
        {view && (
          <section className="m2-support-card">
            <header>
              <div>
                <h2>
                  {view.handoff_status === 'human'
                    ? '人工客服正在陪你处理'
                    : view.handoff_status === 'requested'
                      ? '已留言，等待人工领取'
                      : 'Lumi · 陪伴与帮助'}
                </h2>
                <p>
                  {view.handoff_status === 'bot'
                    ? `${view.development_sample ? '开发样例 · ' : ''}${view.model} · ${connection.state === 'live' ? '已连接' : '正在恢复连接'}`
                    : view.handoff_status === 'requested'
                      ? 'Lumi 仍会继续帮助你；人工领取时间不作承诺。'
                      : '当前由人工回复，你可随时退出人工。'}
                </p>
              </div>
              <div>
                {projectId && <Link to={`/projects/${projectId}/studio`}>回到创作</Link>}
                <button disabled={handoff.isPending} onClick={() => handoff.mutate()}>
                  {view.handoff_status === 'bot'
                    ? '留言请求人工'
                    : view.handoff_status === 'requested'
                      ? '撤回人工留言'
                      : '退出人工'}
                </button>
              </div>
            </header>
            <p className="m2-support-note">
              这里不会启动图片生成或改变拍摄提案。
              {!projectId && '从工作室进入帮助，可查询该项目的次数与任务。'}
            </p>
            <div ref={log} className="m2-support-log" aria-label="客服对话">
              {(cursor === undefined ? view.older_cursor : cursor) && (
                <button disabled={history.isPending} onClick={() => history.mutate()}>
                  查看更早的客服消息
                </button>
              )}
              {!messages.length && (
                <p className="m2-welcome">
                  你好，我是 Lumi。关于准备参考照、创作流程或拍摄规则，都可以慢慢问我。
                </p>
              )}
              {messages.map((message) => (
                <article key={message.id} className={`m2-chat-message m2-role-${message.role}`}>
                  <small>
                    {message.role === 'user'
                      ? '你'
                      : message.role === 'staff'
                        ? '人工客服'
                        : 'Lumi'}
                  </small>
                  <p>{message.text}</p>
                  {message.observations_json && (
                    <ToolObservations observations={message.observations_json} />
                  )}
                  <Citations messageId={message.id} references={message.citations_json} />
                </article>
              ))}
              {active && (
                <article className="m2-chat-message m2-role-assistant" aria-live="polite">
                  <small>Lumi · 正在回复</small>
                  <p>{preview?.text || '正在为你查阅和整理…'}</p>
                </article>
              )}
            </div>
            {view.runs.at(-1) && <RunSteps run={view.runs.at(-1)!} />}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <label htmlFor="support-input">把问题告诉 Lumi</label>
              <textarea
                id="support-input"
                maxLength={1200}
                value={input}
                onChange={(event) => {
                  setInput(event.target.value);
                  pending.current = null;
                }}
                disabled={send.isPending || !!active || !view.enabled}
              />
              <div>
                <span>
                  {view.handoff_status === 'bot'
                    ? '答复有据可查，创作仍由你决定。'
                    : '消息会发送到此客服会话。'}
                </span>
                <button
                  className="button primary"
                  disabled={!input.trim() || send.isPending || !!active || !view.enabled}
                >
                  发送消息
                </button>
              </div>
            </form>
            {errors && <p role="alert">{errors.message}</p>}
            {view.runs.at(-1)?.status === 'failed' && (
              <p role="status">
                本次自动回复未完成。你可以重新提问或请求人工客服。({view.runs.at(-1)?.error_code})
              </p>
            )}
          </section>
        )}
      </Status>
    </div>
  );
}

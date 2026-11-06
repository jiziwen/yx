/** 员工领取客服、文字回复和交还机器人；不显示照片或创作会话。 */
import { useState, useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { Title, State } from '../shared/ui';
export default function SupportPage() {
  const cache = useQueryClient();
  const [id, setId] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [key, setKey] = useState(() => crypto.randomUUID());
  const list = useQuery({
    queryKey: ['staff-support'],
    queryFn: () => api.GET('/api/v1/admin/support').then(expectData),
    refetchInterval: 3000,
  });
  const current = useQuery({
    queryKey: ['staff-support', id],
    enabled: !!id,
    queryFn: () =>
      api
        .GET('/api/v1/admin/support/{conversation_id}', {
          params: { path: { conversation_id: id! } },
        })
        .then(expectData),
    refetchInterval: 2000,
    retry: false,
  });
  const view = current.error ? undefined : current.data;
  const selection = useRef(id);
  selection.current = id;
  useEffect(() => {
    setText('');
    setKey(crypto.randomUUID());
  }, [id, view?.privacy_epoch]);
  const refresh = () => cache.invalidateQueries({ queryKey: ['staff-support'] });
  const action = useMutation({
    mutationFn: async (kind: 'claim' | 'release') => {
      const options = {
        params: { path: { conversation_id: id! } },
        body: { expected_revision: view!.revision },
      };
      return kind === 'claim'
        ? expectData(await api.POST('/api/v1/admin/support/{conversation_id}/claim', options))
        : expectData(await api.POST('/api/v1/admin/support/{conversation_id}/release', options));
    },
    onSuccess: (value) => {
      if (value.id !== selection.current) return;
      if (value.handoff_status === 'bot') {
        setId(null);
        setText('');
      } else cache.setQueryData(['staff-support', value.id], value);
      void refresh();
    },
    onError: () => void refresh(),
  });
  const reply = useMutation({
    mutationFn: () =>
      api
        .POST('/api/v1/admin/support/{conversation_id}/messages', {
          params: { path: { conversation_id: id! } },
          body: {
            expected_revision: view!.revision,
            expected_privacy_epoch: view!.privacy_epoch,
            client_message_id: key,
            text,
          },
        })
        .then(expectData),
    onSuccess: (value) => {
      if (value.id === selection.current) {
        setText('');
        setKey(crypto.randomUUID());
        cache.setQueryData(['staff-support', id], value);
      }
      void refresh();
    },
    onError: () => void refresh(),
  });
  return (
    <>
      <Title
        title="人工客服"
        description="这里只展示用户请求人工的独立客服会话。先领取再回复；交还机器人不会重放旧消息。"
        onRefresh={() => void refresh()}
      />
      <div className="m2-admin-layout">
        <section className="panel">
          <h2>待处理会话</h2>
          {list.error && <State error={list.error} retry={() => void list.refetch()} />}
          <ul className="m2-admin-list">
            {list.data?.map((item) => (
              <li key={item.id}>
                <button
                  aria-pressed={item.id === id}
                  onClick={() => {
                    setId(item.id);
                    setText('');
                    setKey(crypto.randomUUID());
                  }}
                >
                  {item.handoff_status === 'requested' ? '待领取' : '我接管的会话'}
                  <small>
                    {item.id.slice(0, 8)} · {new Date(item.created_at).toLocaleString()}
                  </small>
                </button>
              </li>
            ))}
          </ul>
          {!list.data?.length && <p>当前没有待处理请求。</p>}
        </section>
        <section className="panel">
          {id ? (
            <>
              <State error={current.error} retry={() => void current.refetch()} />
              {view && (
                <>
                  <h2>
                    {view.handoff_status === 'requested' ? '用户正在等待人工' : '人工处理中的会话'}
                  </h2>
                  <p>
                    会话 r{view.revision} ·{' '}
                    {view.project_id ? '已绑定项目，可答疑核对' : '账号客服，无项目资料'}
                  </p>
                  <div className="m2-admin-chat" aria-label="人工客服消息">
                    {view.messages.map((message) => (
                      <article className={'m2-role-' + message.role} key={message.id}>
                        <small>
                          {message.role === 'user'
                            ? '用户'
                            : message.role === 'staff'
                              ? '人工客服'
                              : '机器人'}{' '}
                          · {new Date(message.created_at).toLocaleString()}
                        </small>
                        <p>{message.text}</p>
                      </article>
                    ))}
                  </div>
                  {view.handoff_status === 'requested' ? (
                    <button disabled={action.isPending} onClick={() => action.mutate('claim')}>
                      领取此会话
                    </button>
                  ) : (
                    <>
                      <form
                        className="m2-admin-form"
                        onSubmit={(event) => {
                          event.preventDefault();
                          reply.mutate();
                        }}
                      >
                        <label>
                          人工回复
                          <textarea
                            aria-label="人工回复"
                            rows={4}
                            maxLength={1200}
                            value={text}
                            onChange={(e) => {
                              setText(e.target.value);
                              setKey(crypto.randomUUID());
                            }}
                          />
                        </label>
                        <button disabled={!text.trim() || reply.isPending || action.isPending}>
                          发送人工回复
                        </button>
                      </form>
                      <button
                        className="outline"
                        disabled={reply.isPending || action.isPending}
                        onClick={() => action.mutate('release')}
                      >
                        交还机器人
                      </button>
                    </>
                  )}
                </>
              )}
            </>
          ) : (
            <>
              <h2>在这里，接住用户的问题</h2>
              <p>选择待领取会话后查看文字记录。不会提供照片查看授权、退款或生成权限。</p>
            </>
          )}
          {(reply.error ?? action.error) && (
            <p role="alert">{(reply.error ?? action.error)?.message}</p>
          )}
        </section>
      </div>
    </>
  );
}

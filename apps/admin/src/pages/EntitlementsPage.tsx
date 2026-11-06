/** 管理员按项目补发次数；未知结果保留原请求，刷新后仍可安全重试。 */
import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, expectData, newKey, type GrantInput, type User } from '@yingxu/api-client';
import { Title, State } from '../shared/ui';

/** 只恢复当前管理员的未确认发放，不保存管理凭证。 */
function restore(key: string): GrantInput | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    return value &&
      typeof value.request_key === 'string' &&
      typeof value.user_id === 'string' &&
      typeof value.project_id === 'string' &&
      typeof value.reason === 'string' &&
      Number.isInteger(value.amount) &&
      value.amount > 0 &&
      value.amount <= 10000
      ? value
      : null;
  } catch {
    return null;
  }
}

/** 分页避免仅能从最近100个用户或项目中选择。 */
function Pager({
  offset,
  total,
  onChange,
  disabled = false,
}: {
  offset: number;
  total: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grant-pager">
      <span>
        共 {total} 条 · 第 {Math.floor(offset / 50) + 1} 页
      </span>
      <button
        type="button"
        className="outline"
        disabled={disabled || offset === 0}
        onClick={() => onChange(Math.max(0, offset - 50))}
      >
        上一页
      </button>
      <button
        type="button"
        className="outline"
        disabled={disabled || offset + 50 >= total}
        onClick={() => onChange(offset + 50)}
      >
        下一页
      </button>
    </div>
  );
}

export default function EntitlementsPage() {
  const cache = useQueryClient();
  const actor = cache.getQueryData<User>(['admin-me']);
  const storageKey = `yx:pending-entitlement-grant:${actor?.id}`;
  const [pending, setPending] = useState<GrantInput | null>(() => restore(storageKey));
  const [userId, setUserId] = useState(pending?.user_id ?? '');
  const [projectId, setProjectId] = useState(pending?.project_id ?? '');
  const [amount, setAmount] = useState(String(pending?.amount ?? 8));
  const [reason, setReason] = useState(pending?.reason ?? '');
  const [query, setQuery] = useState(pending?.user_id ?? '');
  const [userOffset, setUserOffset] = useState(0);
  const [projectOffset, setProjectOffset] = useState(0);
  const [recordOffset, setRecordOffset] = useState(0);
  const [message, setMessage] = useState('');
  const inFlight = useRef(false);
  const users = useQuery({
    queryKey: ['grant-users', query, userOffset],
    queryFn: () =>
      api
        .GET('/api/v1/admin/entitlements/users', {
          params: { query: { q: query, offset: userOffset } },
        })
        .then(expectData),
  });
  const projects = useQuery({
    queryKey: ['grant-projects', userId, projectOffset],
    enabled: !!userId,
    queryFn: () =>
      api
        .GET('/api/v1/admin/entitlements/users/{user_id}/projects', {
          params: { path: { user_id: userId }, query: { offset: projectOffset } },
        })
        .then(expectData),
  });
  const records = useQuery({
    queryKey: ['grant-records', userId, projectId, recordOffset],
    queryFn: () =>
      api
        .GET('/api/v1/admin/entitlements/grants', {
          params: {
            query: {
              user_id: userId || undefined,
              project_id: projectId || undefined,
              offset: recordOffset,
            },
          },
        })
        .then(expectData),
  });
  const selectedProject = projects.data?.items.find((item) => item.id === projectId);
  const locked = !!pending;
  const refresh = () => {
    void cache.invalidateQueries({ queryKey: ['grant-projects'] });
    void cache.invalidateQueries({ queryKey: ['grant-records'] });
    void cache.invalidateQueries({ queryKey: ['grant-users'] });
  };
  const clearPending = () => {
    sessionStorage.removeItem(storageKey);
    setPending(null);
  };
  const grant = useMutation({
    mutationFn: (body: GrantInput) =>
      api.POST('/api/v1/admin/entitlements/grants', { body }).then(expectData),
    onSuccess: (record) => {
      clearPending();
      setReason('');
      setRecordOffset(0);
      setMessage(
        `已向「${record.project_title}」发放 ${record.amount} 次，发放后可用 ${record.available_after} 次。记录 ID：${record.id}`,
      );
      refresh();
    },
    onError: (error) => {
      // 确定拒绝的4xx没有发放；断网/5xx可能已提交，必须保留原键核对/重试。
      if (
        error instanceof ApiError &&
        error.status >= 400 &&
        error.status < 500 &&
        error.status !== 408
      )
        clearPending();
      refresh();
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const changeUser = (id: string) => {
    setUserId(id);
    setProjectId('');
    setProjectOffset(0);
    setRecordOffset(0);
    setMessage('');
    grant.reset();
  };
  return (
    <div className="page model-settings">
      <Title
        title="次数发放"
        description="选择客户及所属项目补发可用次数，所有发放保留流水和操作审计。"
        onRefresh={refresh}
      />
      <section className="panel grant-panel">
        <h2>增加项目次数</h2>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (inFlight.current) return;
            const body = pending ?? {
              request_key: newKey(),
              user_id: userId,
              project_id: projectId,
              amount: Number(amount),
              reason: reason.trim(),
            };
            if (
              !pending &&
              (!selectedProject ||
                !Number.isInteger(body.amount) ||
                body.amount < 1 ||
                body.amount > 10000 ||
                !body.reason)
            )
              return;
            // 先持久化请求再发送；刷新或断网后仍复用原键。
            try {
              sessionStorage.setItem(storageKey, JSON.stringify(body));
            } catch {
              setMessage('无法保存发放请求，请允许当前页面使用会话存储后重试。');
              return;
            }
            setMessage('');
            setPending(body);
            inFlight.current = true;
            grant.mutate(body);
          }}
        >
          <fieldset disabled={locked || grant.isPending} className="grant-fields">
            <div className="model-form-grid">
              <label>
                搜索用户昵称或 ID
                <input
                  aria-label="搜索发放用户"
                  value={query}
                  onChange={(event) => {
                    setQuery(event.target.value);
                    setUserOffset(0);
                    changeUser('');
                  }}
                  placeholder="昵称或用户 ID"
                />
              </label>
              <label>
                选择用户
                <select
                  aria-label="选择发放用户"
                  value={userId}
                  onChange={(event) => changeUser(event.target.value)}
                  required
                >
                  <option value="">请选择用户</option>
                  {users.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.display_name} · {item.id}
                    </option>
                  ))}
                  {pending && !users.data?.items.some((item) => item.id === pending.user_id) && (
                    <option value={pending.user_id}>{pending.user_id}</option>
                  )}
                </select>
              </label>
            </div>
            <Pager
              offset={userOffset}
              total={users.data?.total ?? 0}
              onChange={(offset) => {
                setUserOffset(offset);
                changeUser('');
              }}
            />
            {users.isLoading && <p>正在加载用户…</p>}
            {!users.isLoading && !users.error && !users.data?.items.length && (
              <p>未找到可发放的用户。</p>
            )}
            <div className="model-form-grid">
              <label>
                选择项目
                <select
                  aria-label="选择发放项目"
                  value={projectId}
                  disabled={!userId || projects.isLoading}
                  required
                  onChange={(event) => {
                    setProjectId(event.target.value);
                    setRecordOffset(0);
                    setMessage('');
                    grant.reset();
                  }}
                >
                  <option value="">请选择该用户的项目</option>
                  {projects.data?.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title} · {item.id}
                    </option>
                  ))}
                  {pending &&
                    !projects.data?.items.some((item) => item.id === pending.project_id) && (
                      <option value={pending.project_id}>{pending.project_id}</option>
                    )}
                </select>
              </label>
              <label>
                增加次数
                <input
                  aria-label="增加次数"
                  type="number"
                  min={1}
                  max={10000}
                  step={1}
                  value={amount}
                  required
                  onChange={(event) => setAmount(event.target.value)}
                />
              </label>
            </div>
            {userId && (
              <Pager
                offset={projectOffset}
                total={projects.data?.total ?? 0}
                onChange={(offset) => {
                  setProjectOffset(offset);
                  setProjectId('');
                }}
              />
            )}
            {userId && !projects.isLoading && !projects.error && !projects.data?.items.length && (
              <p>该用户暂无有效项目，请先创建或恢复项目。</p>
            )}
            <div className="model-form-grid">
              <label>
                发放原因
                <textarea
                  aria-label="发放原因"
                  value={reason}
                  maxLength={120}
                  required
                  rows={3}
                  placeholder="例如：补充内测创作次数"
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
            </div>
          </fieldset>
          {users.error && <State error={users.error} retry={() => users.refetch()} />}
          {projects.error && <State error={projects.error} retry={() => projects.refetch()} />}
          {selectedProject && (
            <p className="grant-balance">
              「{selectedProject.title}」当前可用{' '}
              <strong>{selectedProject.account.available}</strong> 次 · 预占{' '}
              {selectedProject.account.reserved} 次 · 已用 {selectedProject.account.consumed} 次
            </p>
          )}
          {pending && !grant.isPending && (
            <p className="grant-notice">
              上次发放结果待核对。可先查看下方记录，再重试本次请求；重试不会重复发放。
            </p>
          )}
          {grant.error && (
            <p role="alert" className="error">
              发放未确认：{grant.error.message}
            </p>
          )}
          {message && <p role="status">{message}</p>}
          <button
            className="primary"
            type="submit"
            disabled={grant.isPending || (!pending && (!selectedProject || !reason.trim()))}
          >
            {grant.isPending ? '正在发放…' : pending ? '重试本次发放' : '确认增加次数'}
          </button>
        </form>
      </section>
      <section className="panel grant-panel">
        <h2>发放记录</h2>
        <p className="subtle">
          按当前用户与项目筛选，包含人工补发和内测试用。清空用户选择可查看全部记录。
        </p>
        {records.isLoading ? (
          <State>正在加载记录…</State>
        ) : records.error ? (
          <State error={records.error} retry={() => records.refetch()} />
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {[
                      '时间',
                      '用户 / 项目',
                      '次数',
                      '原因',
                      '来源 / 操作人',
                      '发放后可用',
                      '记录 ID',
                    ].map((label) => (
                      <th key={label}>{label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {records.data?.items.map((item) => (
                    <tr key={item.id}>
                      <td>{new Date(item.created_at).toLocaleString('zh-CN')}</td>
                      <td>
                        {item.user_name}
                        <small className="grant-id">{item.user_id}</small>
                        {item.project_title}
                        <small className="grant-id">{item.project_id}</small>
                      </td>
                      <td>+{item.amount}</td>
                      <td>{item.reason}</td>
                      <td>
                        {item.source === 'manual' ? '人工补发' : '内测试用'}
                        <small className="grant-id">
                          {item.actor_name ?? '系统'}
                          {item.actor_id ? ` · ${item.actor_id}` : ''}
                        </small>
                      </td>
                      <td>{item.available_after ?? '未记录'}</td>
                      <td>{item.id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!records.data?.items.length && <State>暂无发放记录。</State>}
            <Pager
              offset={recordOffset}
              total={records.data?.total ?? 0}
              onChange={setRecordOffset}
            />
          </>
        )}
      </section>
    </div>
  );
}

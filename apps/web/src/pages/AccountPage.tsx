/** 账户身份、退出与实际能力说明；没有购买入口或演示余额。 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { request } from '@yingxu/api-client';
import { RequireUser, useApp } from '../app/context';
import { Heading } from '../shared/ui';
/** 退出撤销服务端会话，同时清除用户资源查询缓存。 */
export default function AccountPage() {
  const { user, catalog, notify } = useApp();
  const client = useQueryClient();
  const logout = useMutation({
    mutationFn: () => request('/web/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      client.clear();
      client.setQueryData(['me'], null);
    },
    onError: (error) => notify(error.message),
  });
  const remove = useMutation({
    mutationFn: () =>
      request('/web/account', { method: 'DELETE', body: JSON.stringify({ confirmed: true }) }),
    onSuccess: () => {
      client.clear();
      window.location.assign('/');
    },
    onError: (error) => notify(error.message),
  });
  return (
    <RequireUser>
      <div className="page-content">
        <Heading
          eyebrow="YOUR PRIVATE ATELIER"
          title="每一个你，都值得珍藏。"
          description="你的身份、创作与私人影像空间。"
        />
        <div className="account-card">
          <div className="profile-orb">{user?.display_name.slice(0, 1)}</div>
          <h2>{user?.display_name}</h2>
          <p className="muted">权益按项目查询，创作前始终需要确认固定方案。</p>
          <p className="notice">
            {catalog.development_mode
              ? '当前为开发环境，图片适配器生成测试卡片。'
              : '私人影像工作室'}
          </p>
          <button className="button" onClick={() => logout.mutate()} disabled={logout.isPending}>
            退出登录
          </button>
          <details>
            <summary>删除账户和全部创作资料</summary>
            <p>
              会删除所有项目、照片、作品、聊天、分析和偏好，不能恢复。已经提交的供应商请求仍需核对，不承诺撤回远端费用。
            </p>
            <button
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm('确认永久删除账户和全部创作资料？')) remove.mutate();
              }}
            >
              确认删除我的账户
            </button>
          </details>
        </div>
      </div>
    </RequireUser>
  );
}

/** 管理端独立功能文件；后端 API 始终校验管理员角色。 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { Aperture, ArrowRight } from 'lucide-react';
/** 管理凭证表单只写请求体，Cookie 为 HttpOnly，不做 localStorage 缓存。 */
export default function Login() {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const cache = useQueryClient();
  const login = useMutation({
    mutationFn: () =>
      api.POST('/api/v1/admin/auth/login', { body: { username, password } }).then(expectData),
    onSuccess: (user) => cache.setQueryData(['admin-me'], user),
  });
  return (
    <div className="admin-login">
      <section>
        <Aperture size={35} strokeWidth={1.3} />
        <p className="eyebrow">LUMIÈRE / OPERATIONS</p>
        <h1>映序管理工作台</h1>
        <p className="subtle">使用受控开通的管理员身份登录。</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <label>
            管理账号
            <input
              aria-label="管理账号"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>
          <label>
            管理密码
            <input
              aria-label="管理密码"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {login.error && (
            <p className="error" role="alert">
              {login.error.message}
            </p>
          )}
          <button className="primary" disabled={login.isPending}>
            {login.isPending ? '验证中…' : '登录工作台'}
            <ArrowRight size={16} />
          </button>
        </form>
        <small className="subtle">用户端登录状态不具备管理权限。</small>
      </section>
    </div>
  );
}

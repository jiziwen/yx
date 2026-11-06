/** 手机验证码开发登录；正式短信服务尚未配置时明确展示当前环境。 */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api, expectData } from '@yingxu/api-client';
import { Modal, Action } from '../../shared/ui';
import { useApp } from '../../app/context';
/** 开发验证码仅展示在弹窗内存中，不写 localStorage。 */
export default function LoginDialog({ onClose }: { onClose: () => void }) {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [debug, setDebug] = useState('');
  const { catalog } = useApp();
  const client = useQueryClient();
  const send = useMutation({
    mutationFn: () => api.POST('/api/v1/web/auth/code', { body: { phone } }).then(expectData),
    onSuccess: (data) => {
      setDebug(data.debug_code);
      setCode(data.debug_code);
    },
  });
  const login = useMutation({
    mutationFn: () =>
      api.POST('/api/v1/web/auth/login', { body: { phone, code } }).then(expectData),
    onSuccess: (user) => {
      client.setQueryData(['me'], user);
      onClose();
    },
  });
  return (
    <Modal title="很高兴，在光里遇见你。" onClose={onClose}>
      <p className="muted">用手机号进入你的私人影像工作室。</p>
      {!catalog.dev_login_enabled ? (
        <p className="notice">短信登录尚未配置，请联系管理员。</p>
      ) : (
        <>
          <p className="notice">开发环境 · 使用本地验证码，不发送真实短信。</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              login.mutate();
            }}
          >
            <label>
              手机号
              <input
                aria-label="手机号"
                type="tel"
                autoComplete="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="请输入手机号"
                required
                pattern="1[3-9][0-9]{9}"
              />
            </label>
            <label>
              验证码
              <div className="input-action">
                <input
                  aria-label="验证码"
                  inputMode="numeric"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  required
                  maxLength={6}
                />
                <button
                  type="button"
                  className="button"
                  disabled={!/^1[3-9]\d{9}$/.test(phone) || send.isPending}
                  onClick={() => send.mutate()}
                >
                  获取验证码
                </button>
              </div>
            </label>
            {debug && <p className="muted">开发验证码：{debug} · 5 分钟内有效</p>}
            {(send.error || login.error) && (
              <p className="error-text" role="alert">
                {(send.error || login.error)?.message}
              </p>
            )}
            <Action type="submit" disabled={login.isPending}>
              {login.isPending ? '正在登录…' : '进入我的工作室'}
            </Action>
          </form>
        </>
      )}
    </Modal>
  );
}

/** 管理端应用壳，身份校验后装配已启用的功能插件。 */
import { Suspense } from 'react';
import { BrowserRouter, NavLink, Routes, Route } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, expectData, ApiError } from '@yingxu/api-client';
import { Aperture, ShieldCheck, LogOut } from 'lucide-react';
import { State } from '../shared/ui';
import Login from '../features/auth/Login';
import { enabledFeatures } from './modules';
/** 先读取独立管理身份，401 才展示登录；网络故障提供重试。 */
export default function App() {
  const identity = useQuery({
    queryKey: ['admin-me'],
    queryFn: async () => {
      try {
        return await api.GET('/api/v1/admin/me').then(expectData);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
  const cache = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api.POST('/api/v1/admin/auth/logout').then(expectData),
    onSuccess: () => {
      cache.clear();
      cache.setQueryData(['admin-me'], null);
    },
  });
  const inventory = useQuery({
    queryKey: ['admin-catalog'],
    queryFn: () => api.GET('/api/v1/admin/catalog').then(expectData),
    enabled: !!identity.data,
  });
  if (identity.isLoading) return <State>正在验证管理会话…</State>;
  if (identity.error) return <State error={identity.error} retry={() => identity.refetch()} />;
  if (!identity.data) return <Login />;
  if (inventory.isLoading) return <State>正在加载管理功能…</State>;
  if (inventory.error) return <State error={inventory.error} retry={() => inventory.refetch()} />;
  const navigation = enabledFeatures(
    inventory.data?.modules.map((module) => module.id) ?? [],
  ).filter((feature) => identity.data?.role !== 'staff' || feature.id === 'support');
  return (
    <BrowserRouter>
      <div className="admin-shell">
        <aside>
          <div className="admin-brand">
            <Aperture size={30} strokeWidth={1.4} />
            <div>
              映序<small>OPERATIONS</small>
            </div>
          </div>
          <p className="nav-caption">工作空间</p>
          <nav>
            {navigation.map((item) => (
              <NavLink end={item.path === '/'} to={item.path} key={item.path}>
                <item.icon size={17} />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="admin-identity">
            <span className="admin-avatar">序</span>
            <div>
              <strong>{identity.data.display_name}</strong>
              <small>{identity.data.role === 'staff' ? '客服员工' : '管理员'} · 独立管理会话</small>
            </div>
            <button aria-label="退出管理登录" onClick={() => logout.mutate()}>
              <LogOut size={16} />
            </button>
          </div>
        </aside>
        <main>
          <header>
            <span>映序管理工作台</span>
            <div>
              <ShieldCheck size={14} />
              服务端权限校验
            </div>
          </header>
          <Suspense fallback={<State>正在加载页面…</State>}>
            <Routes>
              {navigation.map((feature) => (
                <Route key={feature.id} path={feature.path} element={<feature.Page />} />
              ))}
              <Route path="*" element={<State>页面不存在或模块尚未启用。</State>} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}

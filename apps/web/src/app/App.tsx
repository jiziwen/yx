/** 用户端应用壳：正式体验、受控登录与模块路由。 */
import { Suspense, useEffect, useState } from 'react';
import {
  BrowserRouter,
  NavLink,
  Routes,
  Route,
  Link,
  useLocation,
  useNavigate,
} from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, expectData, ApiError } from '@yingxu/api-client';
import { Aperture, ArrowUpRight, Palette, Menu, X, Check, UserRound } from 'lucide-react';
import { AppContext, type CreativeEntry } from './context';
import { enabledFeatures } from './modules';
import { ThemeProvider, useTheme } from '../themes/ThemeProvider';
import { themes } from '../themes/registry';
import { Status, Empty } from '../shared/ui';
import LoginDialog from '../features/auth/LoginDialog';
import FlowerValleyBackground from '../features/ambient/FlowerValleyBackground';
import '../features/ambient/night-appearance.css';
import '../features/atelier/atelier.css';
import '../features/atelier/production.css';
import '../features/atelier/creation.css';
import '../features/atelier/studio.css';
import '../styles/m2-conversations.css';
/** 正式入口统一经过身份、能力目录和主题上下文。 */
export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <Shell />
      </ThemeProvider>
    </BrowserRouter>
  );
}

/** 插件生成导航与路由；切换外观保持页面实例，首页想法仅保存在内存。 */
function Shell() {
  const [loginOpen, setLoginOpen] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [picker, setPicker] = useState(false);
  const [toast, setToast] = useState('');
  const [creativeEntry, setCreativeEntry] = useState<CreativeEntry | null>(null);
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const studio = /^\/projects\/[^/]+\/studio\/?$/.test(location.pathname);
  const catalog = useQuery({
    queryKey: ['catalog'],
    queryFn: () => api.GET('/api/v1/web/catalog').then(expectData),
    refetchInterval: 5000,
    refetchOnWindowFocus: 'always',
  });
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await api.GET('/api/v1/web/me').then(expectData);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
  });
  useEffect(() => {
    setMobile(false);
    setPicker(false);
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [location.pathname]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 5000);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (me.data === null) setCreativeEntry(null);
  }, [me.data]);
  if (!catalog.data)
    return (
      <Status loading={catalog.isLoading} error={catalog.error} retry={() => catalog.refetch()} />
    );
  const features = enabledFeatures(catalog.data);
  return (
    <AppContext.Provider
      value={{
        catalog: catalog.data,
        user: me.data ?? null,
        login: () => setLoginOpen(true),
        notify: setToast,
        creativeEntry,
        setCreativeEntry,
      }}
    >
      <div className={'dream-preview atelier-experience' + (studio ? ' dp-is-studio' : '')}>
        <FlowerValleyBackground subtle={location.pathname !== '/'} />
        <a className="dp-skip" href="#main-content">
          跳到主要内容
        </a>
        <header className="dp-header">
          <Link to="/" className="dp-brand" aria-label="映序首页">
            <span className="dp-brand-icon">
              <Aperture size={25} strokeWidth={1.2} />
            </span>
            <span>
              <strong>映序</strong>
              <small>LUMIÈRE ATELIER</small>
            </span>
          </Link>
          <nav className={'dp-nav at-nav' + (mobile ? ' is-open' : '')} aria-label="主导航">
            {features
              .filter((feature) => feature.label && feature.id !== 'account')
              .map((feature) => (
                <NavLink key={feature.id} to={feature.path} end={feature.path === '/'}>
                  {feature.label}
                  {feature.id === 'projects' && (
                    <span className="dp-nav-spark" aria-hidden="true">
                      ✧
                    </span>
                  )}
                </NavLink>
              ))}
          </nav>
          <div className="dp-header-end at-header-end">
            <div className="at-theme-picker">
              <button
                className="at-theme-trigger"
                onClick={() => setPicker(!picker)}
                aria-expanded={picker}
                aria-label="更换主题外观"
              >
                <Palette size={15} />
                <span>{theme.name}</span>
              </button>
              {picker && (
                <div className="at-theme-menu" aria-label="主题外观">
                  {themes.map((item) => (
                    <button
                      key={item.id}
                      aria-label={'切换主题：' + item.name}
                      aria-pressed={item.id === theme.id}
                      onClick={() => {
                        setTheme(item.id);
                        setPicker(false);
                      }}
                    >
                      <span style={{ background: item.tokens['--accent'] }} />
                      {item.name}
                      {item.id === theme.id && <Check size={13} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              className="at-account"
              aria-label={me.data ? '我的账户' : '登录我的工作室'}
              onClick={() => (me.data ? navigate('/account') : setLoginOpen(true))}
            >
              <UserRound size={15} />
              <span>{me.data ? '我的空间' : '登录'}</span>
            </button>
            <button
              className="at-menu-toggle"
              aria-label={mobile ? '关闭导航' : '打开导航'}
              aria-expanded={mobile}
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={19} /> : <Menu size={19} />}
            </button>
          </div>
        </header>
        <main id="main-content">
          <Suspense fallback={<Status loading />}>
            <Routes>
              {features.map((feature) => (
                <Route key={feature.id} path={feature.path} element={<feature.Page />} />
              ))}
              <Route
                path="*"
                element={
                  <Empty
                    title="这段故事，还没有开始。"
                    description="页面不存在或对应模块尚未启用。"
                    action={
                      <Link className="button" to="/">
                        回到首页
                      </Link>
                    }
                  />
                }
              />
            </Routes>
          </Suspense>
        </main>
        {loginOpen && <LoginDialog onClose={() => setLoginOpen(false)} />}
        <div className="toast-region" aria-live="polite">
          {toast && (
            <div className="toast">
              {toast}
              <button className="icon-button" aria-label="关闭提示" onClick={() => setToast('')}>
                <X size={14} />
              </button>
            </div>
          )}
        </div>
        {!studio && location.pathname !== '/' && (
          <footer className="dp-footer dp-width">
            <Link to="/">映序 LUMIÈRE</Link>
            <span>把心动的模样，慢慢留在光里。</span>
            <Link to="/projects">
              回到我的项目
              <ArrowUpRight size={12} />
            </Link>
          </footer>
        )}
      </div>
    </AppContext.Provider>
  );
}

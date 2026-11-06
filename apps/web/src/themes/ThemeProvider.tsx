/** 主题偏好只持久化非敏感 ID；动画自动超时、可跳过并支持减少动态效果。 */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  Suspense,
  type CSSProperties,
  type ReactNode,
} from 'react';
import { getTheme } from './registry';
import { nightAppearance } from './nightAppearance';
import type { ThemeManifest } from './types';
const Context = createContext<{
  theme: ThemeManifest;
  setTheme: (id: string) => void;
  replay: () => void;
}>(null!);
/** 业务页面跨主题保留实例；不以主题 ID 作为业务路由的 key。 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, update] = useState(() => {
    try {
      return getTheme(localStorage.getItem('yingxu-theme'));
    } catch {
      return getTheme(null);
    }
  });
  const [intro, setIntro] = useState(false);
  useEffect(() => {
    try {
      if (
        !sessionStorage.getItem('yingxu-intro') &&
        !matchMedia('(prefers-reduced-motion: reduce)').matches
      ) {
        setIntro(true);
        sessionStorage.setItem('yingxu-intro', 'seen');
      }
    } catch {
      /* 存储受限仍可正常浏览。 */
    }
  }, []);
  useEffect(() => {
    if (!intro) return;
    const end = () => setIntro(false);
    const timer = setTimeout(end, 2800);
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') end();
    };
    document.addEventListener('keydown', key);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('keydown', key);
    };
  }, [intro, theme.id]);
  /** 新动画替换当前动画，旧计时器由 effect 清理，不残留遮罩。 */
  const setTheme = (id: string) => {
    update(getTheme(id));
    try {
      localStorage.setItem('yingxu-theme', id);
    } catch {
      /* 只影响偏好保存。 */
    }
    setIntro(false);
  };
  const Intro = theme.Intro;
  return (
    <Context.Provider value={{ theme, setTheme, replay: () => setIntro(true) }}>
      <div
        className="studio-theme"
        data-mode="user"
        data-style={theme.id}
        style={
          {
            ...nightAppearance(theme.tokens),
            colorScheme: 'dark',
          } as CSSProperties
        }
      >
        {children}
        {intro && (
          <div
            className="theme-intro"
            role="status"
            aria-label={theme.name + '开场'}
          >
            <Suspense fallback={null}>
              <Intro theme={theme} />
            </Suspense>
            <button className="intro-skip" onClick={() => setIntro(false)}>
              跳过开场 · Esc
            </button>
          </div>
        )}
      </div>
    </Context.Provider>
  );
}
/** 仅共享外观状态，不接触项目、上传、聊天和方案。 */
export function useTheme() {
  return useContext(Context);
}

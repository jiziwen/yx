/** 应用会话和通知入口；所有资源权限仍由后端校验。 */
import { createContext, useContext, type ReactNode } from 'react';
import type { Catalog, User } from '@yingxu/api-client';
export interface AppContextValue {
  catalog: Catalog;
  user: User | null;
  login: () => void;
  notify: (message: string) => void;
  creativeEntry: CreativeEntry | null;
  setCreativeEntry: (entry: CreativeEntry | null) => void;
}
/** 首页想法只留在应用内存，并在创建后绑定项目，不进入 URL 或浏览器存储。 */
export interface CreativeEntry {
  brief: string;
  styleId?: string;
  projectId?: string;
  mode?: 'template' | 'portrait' | 'edit' | 'text';
  shotIds?: string[];
  styleShotIds?: string[];
}
export const AppContext = createContext<AppContextValue>(null!);
/** 页面消费启动能力与当前用户，不保存照片或凭证。 */
export function useApp() {
  return useContext(AppContext);
}
/** 登录前可浏览页面，执行动作时明确建立身份。 */
export function RequireUser({ children }: { children: ReactNode }) {
  const { user, login } = useApp();
  return user ? (
    <>{children}</>
  ) : (
    <div className="empty-state">
      <span className="eyebrow">A SPACE OF YOUR OWN</span>
      <h2>给故事，一个专属空间。</h2>
      <p>登录后继续你的项目、参考照片与作品。</p>
      <button className="button primary" onClick={login}>
        登录，开启我的故事 ↗
      </button>
    </div>
  );
}

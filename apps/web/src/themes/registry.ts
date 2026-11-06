/** 自动发现主题插件；新增目录不需要修改注册表或业务页面。 */
import type { ThemeManifest } from './types';
import { experience } from '../config/experience';
const entries = import.meta.glob<{ default: ThemeManifest }>('./*/manifest.ts', { eager: true });
export const themes = Object.values(entries)
  .map((entry) => entry.default)
  .filter((theme) => theme.enabled !== false)
  .sort((a, b) => a.order - b.order);
if (!themes.length || new Set(themes.map((theme) => theme.id)).size !== themes.length)
  throw new Error('主题为空或 ID 重复');
export const defaultTheme =
  themes.find((theme) => theme.id === experience.defaultThemeId) ?? themes[0];
/** 无效/已移除的偏好安全回退，禁止从 localStorage 加载任意组件。 */
export function getTheme(id: string | null) {
  return themes.find((theme) => theme.id === id) ?? defaultTheme;
}

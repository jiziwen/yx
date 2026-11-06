/** 管理功能自动注册；菜单与路由共同依赖后端实际安装模块。 */
import type { ComponentType } from 'react';
import type { LucideIcon } from 'lucide-react';
export interface AdminFeature {
  id: string;
  path: string;
  label: string;
  icon: LucideIcon;
  order: number;
  requires: string[];
  Page: ComponentType;
}
const manifests = import.meta.glob<{ default: AdminFeature }>('../features/*/manifest.tsx', {
  eager: true,
});
const features = Object.values(manifests)
  .map((entry) => entry.default)
  .sort((a, b) => a.order - b.order);
if (new Set(features.map((feature) => feature.id)).size !== features.length)
  throw new Error('管理功能 ID 重复');
/** 关闭后台相关业务模块后，导航和页面也同步移除。 */
export function enabledFeatures(modules: string[]) {
  return features.filter((feature) => feature.requires.every((id) => modules.includes(id)));
}

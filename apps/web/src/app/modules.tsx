/** 前端功能插件注册；菜单和路由从同一清单生成，关闭服务端模块即关闭入口。 */
import { lazy, type ComponentType } from 'react';
import { Compass, FolderHeart, BookOpen, Gift, UserRound, type LucideIcon } from 'lucide-react';
import type { Catalog } from '@yingxu/api-client';
export interface Feature {
  id: string;
  path: string;
  label?: string;
  order?: number;
  icon?: LucideIcon;
  requires: string[];
  flag?: string;
  Page: ReturnType<typeof lazy<ComponentType>>;
}
const entries = import.meta.glob<{ default: Feature[] }>('../modules/*/manifest.tsx', {
  eager: true,
});
const features = Object.values(entries)
  .flatMap((entry) => entry.default)
  .sort((left, right) => (left.order ?? 100) - (right.order ?? 100));
if (new Set(features.map((feature) => feature.id)).size !== features.length)
  throw new Error('前端功能 ID 重复');
/** 同时过滤导航与路由；API 权限仍必须由后端验证。 */
export function enabledFeatures(catalog: Catalog) {
  return features.filter(
    (feature) =>
      feature.requires.every((id) => catalog.modules.includes(id)) &&
      (!feature.flag || catalog.features[feature.flag]),
  );
}
export { Compass, FolderHeart, BookOpen, Gift, UserRound, lazy };

/** 模块与配置插件清单；自动发现并按 order 排列。 */
import { lazy } from 'react';
import { Blocks } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'catalog',
  path: '/catalog',
  label: '模块与配置',
  icon: Blocks,
  order: 3,
  requires: ['operations'],
  Page: lazy(() => import('../../pages/CatalogPage')),
};
export default feature;

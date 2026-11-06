/** 模型设置独立页面，由服务端 operations 权限与版本发布约束。 */
import { lazy } from 'react';
import { SlidersHorizontal } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'models',
  path: '/models',
  label: '302.AI 模型',
  icon: SlidersHorizontal,
  order: 3,
  requires: ['operations'],
  Page: lazy(() => import('../../pages/ModelsPage')),
};
export default feature;

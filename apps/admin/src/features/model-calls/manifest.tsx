/** 模型调用独立菜单，随 operations 模块装配。 */
import { lazy } from 'react';
import { Activity } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'model-calls',
  path: '/model-calls',
  label: '模型调用',
  icon: Activity,
  order: 3.1,
  requires: ['operations'],
  Page: lazy(() => import('../../pages/ModelCallsPage')),
};
export default feature;

/** 运营概览插件清单；自动发现并按 order 排列。 */
import { lazy } from 'react';
import { LayoutDashboard } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'overview',
  path: '/',
  label: '运营概览',
  icon: LayoutDashboard,
  order: 0,
  requires: ['operations'],
  Page: lazy(() => import('../../pages/OverviewPage')),
};
export default feature;

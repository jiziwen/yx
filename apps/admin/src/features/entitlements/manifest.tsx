/** 次数发放独立注册，业务模块关闭时隐藏入口。 */
import { lazy } from 'react';
import { TicketPlus } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'entitlements',
  path: '/entitlements',
  label: '次数发放',
  icon: TicketPlus,
  order: 1.5,
  requires: ['operations', 'commerce', 'projects'],
  Page: lazy(() => import('../../pages/EntitlementsPage')),
};
export default feature;

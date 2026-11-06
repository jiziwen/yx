/** 人工客服独立菜单，staff/admin可用，管理发布仍限admin。 */
import { lazy } from 'react';
import { MessagesSquare } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';
const feature: AdminFeature = {
  id: 'support',
  path: '/support',
  label: '人工客服',
  icon: MessagesSquare,
  order: 5,
  requires: ['conversations'],
  Page: lazy(() => import('../../pages/SupportPage')),
};
export default feature;

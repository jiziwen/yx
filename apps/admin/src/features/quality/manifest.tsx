/** 最小质量服务入口复用operations权限边界。 */
import { lazy } from 'react';
import { MessageSquare } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';
const feature: AdminFeature = {
  id: 'quality',
  path: '/quality',
  label: '质量反馈',
  icon: MessageSquare,
  order: 8,
  requires: ['operations'],
  Page: lazy(() => import('../../pages/QualityPage')),
};
export default feature;

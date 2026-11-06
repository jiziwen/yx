/** 知识管理独立插件；只有管理员可发布，下架同步影响检索。 */
import { lazy } from 'react';
import { BookOpenCheck } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';
const feature: AdminFeature = {
  id: 'knowledge',
  path: '/knowledge',
  label: '知识库',
  icon: BookOpenCheck,
  order: 4,
  requires: ['knowledge'],
  Page: lazy(() => import('../../pages/KnowledgePage')),
};
export default feature;

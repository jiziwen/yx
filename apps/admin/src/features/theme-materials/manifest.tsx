/** 动态主题素材管理，目录及运营模块共同启用时注册。 */
import { lazy } from 'react';
import { Images } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const feature: AdminFeature = {
  id: 'theme-materials',
  path: '/theme-materials',
  label: '主题素材',
  icon: Images,
  order: 2.5,
  requires: ['operations', 'catalog'],
  Page: lazy(() => import('../../pages/ThemeMaterialsPage')),
};
export default feature;

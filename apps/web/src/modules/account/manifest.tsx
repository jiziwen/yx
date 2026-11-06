/** account 功能插件入口；导航、路由、服务端依赖由同一个清单维护。 */
import { lazy } from 'react';
import { UserRound } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'account',
    order: 60,
    path: '/account',
    label: '我的账户',
    icon: UserRound,
    requires: ['identity'],
    Page: lazy(() => import('../../pages/AccountPage')),
  },
];
export default features;

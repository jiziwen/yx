/** gifts 功能插件入口；导航、路由、服务端依赖由同一个清单维护。 */
import { lazy } from 'react';
import { Gift } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'gifts',
    order: 50,
    path: '/gifts',
    label: '专属礼物',
    icon: Gift,
    requires: [],
    flag: 'gifts_enabled',
    Page: lazy(() => import('../../pages/GiftsPage')),
  },
];
export default features;

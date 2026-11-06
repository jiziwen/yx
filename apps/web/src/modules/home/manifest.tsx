/** home 功能插件入口；导航、路由、服务端依赖由同一个清单维护。 */
import { lazy } from 'react';
import { Compass } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'home',
    order: 0,
    path: '/',
    label: '发现灵感',
    icon: Compass,
    requires: ['catalog'],
    Page: lazy(() => import('../../pages/HomePage')),
  },
];
export default features;

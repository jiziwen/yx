/** guides 功能插件入口；导航、路由、服务端依赖由同一个清单维护。 */
import { lazy } from 'react';
import { BookOpen } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'guides',
    order: 30,
    path: '/guides',
    label: '灵感指南',
    icon: BookOpen,
    requires: ['knowledge'],
    Page: lazy(() => import('../../pages/GuidesPage')),
  },
];
export default features;

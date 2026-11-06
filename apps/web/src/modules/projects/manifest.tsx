/** projects 功能插件入口；导航、路由、服务端依赖由同一个清单维护。 */
import { lazy } from 'react';
import { FolderHeart } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'inspiration',
    order: 10,
    path: '/inspiration',
    label: '灵感库',
    requires: ['catalog'],
    Page: lazy(() => import('../../pages/InspirationPage')),
  },
  {
    id: 'projects',
    order: 20,
    path: '/projects',
    label: '我的项目',
    icon: FolderHeart,
    requires: ['projects'],
    Page: lazy(() => import('../../pages/ProjectsPage')),
  },
  {
    id: 'studio',
    path: '/projects/:projectId/studio',
    requires: ['projects', 'assets', 'executions', 'media_jobs'],
    Page: lazy(() => import('../../pages/StudioPage')),
  },
  {
    id: 'works',
    path: '/projects/:projectId/works',
    requires: ['media_jobs', 'assets'],
    Page: lazy(() => import('../../pages/WorksPage')),
  },
];
export default features;

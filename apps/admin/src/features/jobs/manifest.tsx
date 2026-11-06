/** 生成任务插件清单；自动发现并按 order 排列。 */
import { lazy } from 'react';
import { Image } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const Records = lazy(() => import('../../pages/RecordsPage'));
/** 复用只读表格，模块清单决定具体业务入口。 */
function JobsPage() {
  return <Records kind="jobs" />;
}

const feature: AdminFeature = {
  id: 'jobs',
  path: '/jobs',
  label: '生成任务',
  icon: Image,
  order: 2,
  requires: ['operations'],
  Page: JobsPage,
};
export default feature;

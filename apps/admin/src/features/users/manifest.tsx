/** 用户与项目插件清单；自动发现并按 order 排列。 */
import { lazy } from 'react';
import { Users } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const Records = lazy(() => import('../../pages/RecordsPage'));
/** 复用只读表格，模块清单决定具体业务入口。 */
function UserPage() {
  return <Records kind="users" />;
}

const feature: AdminFeature = {
  id: 'users',
  path: '/users',
  label: '用户与项目',
  icon: Users,
  order: 1,
  requires: ['operations'],
  Page: UserPage,
};
export default feature;

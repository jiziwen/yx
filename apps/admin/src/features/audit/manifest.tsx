/** 操作审计插件清单；自动发现并按 order 排列。 */
import { lazy } from 'react';
import { ScrollText } from 'lucide-react';
import type { AdminFeature } from '../../app/modules';

const Records = lazy(() => import('../../pages/RecordsPage'));
/** 复用只读表格，模块清单决定具体业务入口。 */
function AuditPage() {
  return <Records kind="audit" />;
}

const feature: AdminFeature = {
  id: 'audit',
  path: '/audit',
  label: '操作审计',
  icon: ScrollText,
  order: 4,
  requires: ['operations'],
  Page: AuditPage,
};
export default feature;

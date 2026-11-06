/** 独立客服功能由服务端模块和开关装配；不影响原创作会话。 */
import { lazy } from 'react';
import { MessagesSquare } from 'lucide-react';
import type { Feature } from '../../app/modules';
const features: Feature[] = [
  {
    id: 'support',
    order: 40,
    path: '/support',
    label: '陪伴与帮助',
    icon: MessagesSquare,
    requires: ['conversations', 'agents'],
    flag: 'support_enabled',
    Page: lazy(() => import('../../pages/SupportPage')),
  },
];
export default features;

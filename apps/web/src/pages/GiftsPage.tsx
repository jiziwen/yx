/** 赠品功能扩展入口；未启用时前端注册表移除此路由和菜单。 */
import { Heading, Empty } from '../shared/ui';
/** 实际渲染与权益契约完成后替换此等待状态。 */
export default function GiftsPage() {
  return (
    <div className="page-content">
      <Heading
        eyebrow="MORE THAN A PHOTOGRAPH"
        title="喜欢之外，再多一点惊喜。"
        description="头像、壁纸、海报与照片合集。"
      />
      <Empty title="一份心意，正在准备。" description="赠品渲染模块尚未接入，当前无法制作。" />
    </div>
  );
}

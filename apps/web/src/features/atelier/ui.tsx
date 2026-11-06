/** 共享的摄影师标识；抽离于路由入口，避免页面相互循环依赖。 */
import { Sparkles } from 'lucide-react';

/** 抽象光点头像表达 AI 身份，不冒用真实摄影师照片。 */
export function LumiAvatar({ small = false }: { small?: boolean }) {
  return (
    <span className={'dp-lumi-avatar' + (small ? ' dp-avatar-small' : '')} aria-hidden="true">
      <Sparkles strokeWidth={1.4} />
    </span>
  );
}

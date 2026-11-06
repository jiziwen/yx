/** 轻量主题入场内容；跳过、Escape 和自动结束由 ThemeProvider 统一管理。 */
import type { ThemeIntroProps } from '../types';
/** 只绘制当前主题的氛围，避免各插件重复实现交互控制。 */
export default function Intro({ theme }: ThemeIntroProps) {
  return (
    <div className="intro-art">
      <img src={theme.image} alt="" />
      <span>{theme.english}</span>
      <h1>{theme.name}</h1>
      <p>{theme.description}</p>
    </div>
  );
}

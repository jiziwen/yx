/** 正式首页的共享梦幻构图；主题可替换整个 Hero，文案与素材来自 manifest。 */
import { useState, type FormEvent } from 'react';
import { ArrowUpRight, Heart, Sparkles } from 'lucide-react';
import type { ThemeHeroProps } from '../../themes/types';
import { experience } from '../../config/experience';
import { LumiAvatar } from './ui';

/** 首页只收集初始想法，创建项目与付费动作仍由各自业务入口处理。 */
export default function DreamHero({ theme, onCreate, onStart }: ThemeHeroProps) {
  const [brief, setBrief] = useState('');
  const headline = theme.atelier?.headline ?? ['把心动的模样，', '拍成一场梦。'];
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (onStart) onStart(brief.trim());
    else onCreate(theme);
  };
  return (
    <section className="dp-hero dp-width">
      <div className="dp-hero-copy">
        <span className="dp-eyebrow">
          <span className="dp-tiny-star">✧</span>YOUR STORY, SOFTLY IN FOCUS
        </span>
        <h1>
          {headline[0]}
          <br />
          <em>{headline[1]}</em>
          <span className="dp-heading-star" aria-hidden="true">
            ✧
          </span>
        </h1>
        <p className="dp-hero-description">
          {theme.atelier?.subtitle ?? '不必懂镜头，也不用想好答案。'}
          <br />
          和你的专属 AI 摄影师聊聊，让想象慢慢成为照片。
        </p>
        <form className="dp-invitation" onSubmit={submit}>
          <div className="dp-invitation-intro">
            <LumiAvatar small />
            <span>
              我是 {experience.photographer.name}，你的 AI 摄影师。
              <br />
              <strong>今天，想遇见怎样的自己？</strong>
            </span>
          </div>
          <textarea
            aria-label={`告诉 ${experience.photographer.name} 你的拍摄想法`}
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder="想去海边、想拍纪念日，或者只是想看看不一样的自己……"
            maxLength={experience.guide.maxInputLength}
            rows={2}
          />
          <div className="dp-invitation-bottom">
            <span>
              <span className="dp-online-dot" />
              从一句话，开始我们的创作
            </span>
            <button
              className="dp-send"
              aria-label={`和 ${experience.photographer.name} 开始创作`}
              type="submit"
            >
              <ArrowUpRight size={21} />
            </button>
          </div>
        </form>
        <div className="dp-prompt-chips" aria-label="试试这些拍摄想法">
          {['想拍一组海边情侣照', '想看看电影里的自己', '还没有想法，带我找找灵感'].map((text) => (
            <button key={text} onClick={() => setBrief(text)}>
              <Sparkles size={11} />
              {text}
            </button>
          ))}
        </div>
        <div className="dp-hero-footnote">
          <Heart size={13} strokeWidth={1.5} />
          <span>先聊聊，再决定。每一个画面，都由你确认。</span>
        </div>
      </div>
      <div className="dp-hero-art" aria-label={theme.name + '风格示例'}>
        <div className="dp-orbit dp-orbit-one" aria-hidden="true" />
        <div className="dp-orbit dp-orbit-two" aria-hidden="true" />
        <span className="dp-art-star dp-art-star-one" aria-hidden="true">
          ✧
        </span>
        <span className="dp-art-star dp-art-star-two" aria-hidden="true">
          ✦
        </span>
        <div className="dp-hero-portrait">
          <img
            src={theme.atelier?.coverImage ?? theme.image}
            style={{ objectPosition: theme.atelier?.coverPosition }}
            alt={theme.name + '风格样片，非用户作品'}
            fetchPriority="high"
          />
          <span className="dp-photo-label">a little dream, a little you.</span>
          <div className="dp-image-glow" />
        </div>
        <div className="dp-floating-note">
          <span className="dp-note-icon">
            <Sparkles size={15} />
          </span>
          <div>
            <strong>光线再柔和一点，</strong>
            <span>让这一刻，更像你。</span>
          </div>
        </div>
        <div className="dp-polaroid">
          <img src={theme.atelier?.secondaryImage ?? theme.secondary} alt="辅助灵感样片" />
          <div>
            <span>{theme.signature}</span>
            <Heart size={13} />
          </div>
        </div>
        <span className="dp-art-caption">MADE OF LIGHT & LITTLE FEELINGS</span>
        <div className="dp-art-palette" aria-hidden="true">
          {(
            theme.atelier?.palette ?? [
              theme.tokens['--accent'],
              theme.tokens['--surface-up'],
              theme.tokens['--bg'],
            ]
          ).map((color, index) => (
            <i key={index} style={{ background: color }} />
          ))}
          <span>今日的温柔色谱</span>
        </div>
      </div>
    </section>
  );
}

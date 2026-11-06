/** 从参考 UI 迁移的六种艺术构图，只负责展示，不持有项目状态。 */
import { ArrowUpRight } from 'lucide-react';
import type { ThemeHeroProps } from '../types';
import type { ImgHTMLAttributes, ReactNode } from 'react';

const IMAGE_FALLBACKS: Record<string, string> = {
  rose: '/images/hero-coast.webp',
  film: '/images/hero-coast.webp',
  portrait: '/images/editorial-portrait.webp',
  fresh: '/images/editorial-portrait.webp',
  coast: '/images/hero-coast.webp',
  oriental: '/images/oriental-wedding.webp',
};

/** 按需加载主题样片，加载失败时只回退一次。 */
function EditorialImage({
  src,
  themeId,
  alt,
  className = '',
  eager = false,
  ...props
}: ImgHTMLAttributes<HTMLImageElement> & { themeId: string; eager?: boolean }) {
  return (
    <img
      src={src}
      alt={alt}
      className={className}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
      {...props}
      onError={(event) => {
        const fallback = IMAGE_FALLBACKS[themeId];
        if (fallback && !event.currentTarget.dataset.fallback) {
          event.currentTarget.dataset.fallback = 'true';
          event.currentTarget.src = fallback;
        }
      }}
    />
  );
}

/** 共用文案与动作位置；主题不接管确认等业务行为。 */
function HeroCopy({ theme, onCreate, busy, children }: ThemeHeroProps & { children?: ReactNode }) {
  return (
    <div className="ed-hero-copy">
      <div className="ed-kicker">
        <span />
        {theme.english}
        <span className="ed-kicker-type">{theme.tag}</span>
      </div>
      <h1>
        {theme.headline.map((line, i) => (
          <span key={line} className={i ? 'ed-title-accent' : ''}>
            {line}
          </span>
        ))}
      </h1>
      <p className="ed-hero-description">{theme.subtitle}</p>
      <div className="ed-hero-actions">
        <button className="ed-primary" onClick={() => onCreate(theme)} disabled={busy}>
          {busy ? '创作正在进行' : '开始我的创作'}
          <ArrowUpRight size={19} strokeWidth={1.5} aria-hidden="true" />
        </button>
        <span className="ed-demo-note">风格样片 · 以你的故事开始</span>
      </div>
      {children}
    </div>
  );
}

/** 现有艺术构图的可复用渲染器，新主题可选择复用或独立提供组件。 */
export default function EditorialHero({ theme, onCreate, busy }: ThemeHeroProps) {
  const props = { theme, onCreate, busy };
  const photo = (
    <EditorialImage src={theme.image} themeId={theme.id} alt={`${theme.name}风格摄影示例`} eager />
  );

  if (theme.layout === 'cinema')
    return (
      <section className="ed-hero ed-hero-film" aria-label={theme.name + '风格介绍'}>
        <div className="ed-cinema-scene">{photo}</div>
        <div className="ed-cinema-shade" />
        <div className="ed-hero-inner ed-cinema-content">
          <HeroCopy {...props}>
            <p className="ed-signature ed-cinema-signature">{theme.signature}</p>
          </HeroCopy>
        </div>
        <div className="ed-film-index">
          <span>SCENE 02</span>
          <i />
          <span>一帧光影，一场心动。</span>
          <span className="ed-film-format">A LOVE STORY IN LIGHT</span>
        </div>
      </section>
    );

  if (theme.layout === 'muse')
    return (
      <section className="ed-hero ed-hero-muse ed-hero-inner" aria-label={theme.name + '风格介绍'}>
        <HeroCopy {...props}>
          <span className="ed-muse-footnote">
            A PORTRAIT, A POEM.
            <br />
            关于你，不止一种模样。
          </span>
        </HeroCopy>
        <div className="ed-muse-diptych">
          <figure className="ed-muse-main ed-photo-window">
            {photo}
            <figcaption>01 — IN YOUR OWN LIGHT</figcaption>
          </figure>
          <figure className="ed-muse-detail ed-photo-window">
            <EditorialImage
              src={theme.image}
              themeId={theme.id}
              alt="柔光肖像的丝绸与光影细节"
              eager
            />
          </figure>
          <span className="ed-signature ed-muse-signature" aria-hidden="true">
            muse.
          </span>
          <span className="ed-vertical-note">THE ART OF BEING YOU</span>
        </div>
      </section>
    );

  if (theme.layout === 'fresh')
    return (
      <section className="ed-hero ed-hero-fresh ed-hero-inner" aria-label={theme.name + '风格介绍'}>
        <div className="ed-leaf-shadow" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
        <HeroCopy {...props}>
          <p className="ed-fresh-note">
            <span className="ed-signature">Dear sunshine,</span>
            <br />
            今天，把喜欢的自己寄给未来。
          </p>
        </HeroCopy>
        <div className="ed-postcard-stack">
          <span className="ed-postcard-under" aria-hidden="true" />
          <figure className="ed-postcard">
            <div className="ed-photo-window">{photo}</div>
            <figcaption>
              <span>一些刚刚好的日常</span>
              <span className="ed-signature">with love.</span>
            </figcaption>
          </figure>
          <span className="ed-postcard-stamp" aria-hidden="true">
            晴<br />日
          </span>
          <span className="ed-postcard-caption">A LITTLE SUNSHINE, JUST FOR YOU.</span>
        </div>
      </section>
    );

  if (theme.layout === 'coast')
    return (
      <section className="ed-hero ed-hero-coast ed-hero-inner" aria-label={theme.name + '风格介绍'}>
        <HeroCopy {...props} />
        <figure className="ed-coast-panorama ed-photo-window">
          {photo}
          <figcaption>
            <span className="ed-signature">Somewhere, with you.</span>
            <span>海风、日落，以及我们。</span>
          </figcaption>
        </figure>
        <span className="ed-coast-coordinate">A STORY BY THE SEA</span>
      </section>
    );

  if (theme.layout === 'oriental')
    return (
      <section
        className="ed-hero ed-hero-oriental ed-hero-inner"
        aria-label={theme.name + '风格介绍'}
      >
        <HeroCopy {...props}>
          <div className="ed-oriental-note">
            <span>囍</span>
            <p>
              让东方的留白
              <br />
              盛放一生的浪漫
            </p>
          </div>
        </HeroCopy>
        <div className="ed-oriental-art">
          <span className="ed-oriental-disc" aria-hidden="true" />
          <figure className="ed-oriental-photo ed-photo-window">{photo}</figure>
          <span className="ed-seal">
            良辰
            <br />
            喜事
          </span>
          <span className="ed-oriental-caption">执手 · 共此良辰</span>
          <span className="ed-vertical-note">A MODERN LOVE, AN ENDLESS STORY</span>
        </div>
      </section>
    );

  return (
    <section className="ed-hero ed-hero-rose ed-hero-inner" aria-label={theme.name + '风格介绍'}>
      <HeroCopy {...props}>
        <div className="ed-rose-postscript">
          <span className="ed-signature">Moments</span>
          <p>
            把一瞬心动
            <br />
            写成永恒的序章
          </p>
        </div>
      </HeroCopy>
      <div className="ed-rose-art">
        <figure className="ed-rose-main ed-photo-window">
          {photo}
          <figcaption>THE POETRY OF US</figcaption>
        </figure>
        <figure className="ed-rose-inset">
          <EditorialImage
            src="/images/theme-muse.webp"
            themeId="portrait"
            alt="柔光人像作品局部"
            eager
          />
          <figcaption>softly, forever.</figcaption>
        </figure>
        <span className="ed-rose-photo-note">光影成诗 · 爱意成像</span>
        <span className="ed-vertical-note">LUMIÈRE — THE ART OF YOUR STORY</span>
      </div>
    </section>
  );
}

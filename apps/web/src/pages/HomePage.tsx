/** 正式梦幻首页：主题渲染由插件决定，创作风格由服务端目录决定。 */
import { Suspense, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  Heart,
  MessageCircle,
  RotateCcw,
  WandSparkles,
} from 'lucide-react';
import { useTheme } from '../themes/ThemeProvider';
import { themes } from '../themes/registry';
import type { ThemeManifest } from '../themes/types';
import { useApp, type CreativeEntry } from '../app/context';
import { LumiAvatar } from '../features/atelier/ui';
import { experience } from '../config/experience';
import CreationEntries from '../features/atelier/CreationEntries';

/** 首页不写项目；先登录、命名并确认项目类型，再将想法绑定到新项目。 */
export default function HomePage() {
  const { theme, setTheme, replay } = useTheme();
  const { catalog, user, login, setCreativeEntry } = useApp();
  const navigate = useNavigate();
  const [filter, setFilter] = useState('all');
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState<CreativeEntry | null>(null);
  const Hero = theme.Hero;
  const styles = catalog.styles;
  const filtered = styles.filter((style) => filter === 'all' || style.kind === filter);
  const visible = expanded || filter !== 'all' ? filtered : filtered.slice(0, 3);
  const enter = (entry: CreativeEntry) => {
    setCreativeEntry(entry);
    navigate(
      '/projects?new=1' + (entry.styleId ? '&style=' + encodeURIComponent(entry.styleId) : ''),
    );
  };
  useEffect(() => {
    if (user && pending) {
      enter(pending);
      setPending(null);
    }
  }, [user, pending]); // 保留登录前的显式创作意图。
  const start = (brief = '', styleId?: string) => {
    const entry = { brief, styleId };
    if (user) enter(entry);
    else {
      setPending(entry);
      login();
    }
  };
  const create = (selected: ThemeManifest) => {
    const style = styles.find((item) => item.theme_id === selected.id);
    start('', style?.id);
  };
  return (
    <>
      <Suspense fallback={<div className="hero-placeholder" />}>
        <Hero theme={theme} onCreate={create} onStart={(brief) => start(brief)} />
      </Suspense>
      <div className="dp-downline dp-width">
        <span>灵感不用急着想好，我们一起找。</span>
        <a href="#at-inspiration" aria-label="向下探索灵感">
          <ArrowDown size={17} />
        </a>
      </div>
      <CreationEntries
        onChoose={(mode) => {
          if (mode === 'template') navigate('/inspiration');
          else {
            const entry: CreativeEntry = { brief: '', mode };
            if (user) enter(entry);
            else {
              setPending(entry);
              login();
            }
          }
        }}
      />
      <section className="dp-inspiration dp-width" id="at-inspiration">
        <div className="dp-section-heading">
          <div>
            <span className="dp-eyebrow">A MOOD TO FALL INTO</span>
            <h2>
              先让一张照片，<em>替你说说心情。</em>
            </h2>
          </div>
          <div className="dp-filter" aria-label="筛选创作灵感">
            {[
              ['all', '全部灵感'],
              ['portrait', '一个人的小宇宙'],
              ['wedding', '两个人的故事'],
            ].map(([id, label]) => (
              <button
                key={id}
                aria-pressed={filter === id}
                className={filter === id ? 'is-active' : ''}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="dp-mood-grid">
          {visible.map((style, index) => {
            const visual = themes.find((item) => item.id === style.theme_id) ?? theme;
            return (
              <button
                className="dp-mood-card"
                key={style.id}
                aria-label={'用' + style.name + '创作'}
                onClick={() => {
                  navigate('/inspiration?style=' + encodeURIComponent(style.id));
                }}
              >
                <div className="dp-mood-image">
                  <img src={style.image} alt={style.name + '风格样片'} loading="lazy" />
                  <span className="dp-mood-number">0{index + 1} / INSPIRATION</span>
                  <span className="dp-mood-open">
                    <ArrowUpRight size={21} />
                  </span>
                  <span className="dp-mood-image-caption">{visual.english}</span>
                </div>
                <div className="dp-mood-title">
                  <h3>{style.name}</h3>
                  <span className="dp-color-dots" aria-hidden="true">
                    {(
                      visual.atelier?.palette ?? [
                        visual.tokens['--accent'],
                        visual.tokens['--surface-up'],
                        visual.tokens['--bg'],
                      ]
                    ).map((color, i) => (
                      <i key={i} style={{ background: color }} />
                    ))}
                  </span>
                </div>
                <p>{visual.description}</p>
                <small>
                  {style.kind === 'wedding' ? '双人婚纱 / 情侣影像' : '私人肖像'} · {style.mood}
                </small>
              </button>
            );
          })}
        </div>
        {filter === 'all' && filtered.length > 3 && (
          <button className="dp-more-moods" onClick={() => setExpanded(!expanded)}>
            {expanded ? '收起灵感' : '更多心情，慢慢探索'}
            <ArrowRight size={15} />
          </button>
        )}
      </section>
      <section className="at-appearance dp-width">
        <span className="dp-eyebrow">A SPACE THAT FEELS LIKE YOU</span>
        <div>
          <h2>给创作空间，换一种心情。</h2>
          <button onClick={replay}>
            <RotateCcw size={12} />
            重播开场
          </button>
        </div>
        <p>这里切换界面外观；已选的创作风格、人物和提案都为你保留。</p>
        <div className="at-theme-strip">
          {themes.map((item) => (
            <button
              key={item.id}
              aria-label={'切换主题：' + item.name}
              aria-pressed={theme.id === item.id}
              onClick={() => setTheme(item.id)}
            >
              <span style={{ background: item.tokens['--scene-secondary'] }} />
              {item.name}
              {theme.id === item.id && <Check size={12} />}
            </button>
          ))}
        </div>
      </section>
      <section className="dp-companion dp-width">
        <div className="dp-companion-intro">
          <LumiAvatar />
          <span className="dp-eyebrow">A PHOTOGRAPHER WHO LISTENS</span>
          <h2>
            你负责做自己，
            <br />
            <em>我陪你找到光。</em>
          </h2>
          <p>
            从“我也说不清想要什么”，
            <br />
            到“对，就是这种感觉”。
          </p>
          <button className="dp-primary" onClick={() => start()}>
            开始我的创作
            <ArrowUpRight size={16} />
          </button>
          <p className="at-guide-disclosure">
            {catalog.features.chat_enabled
              ? '和 Lumi 一起整理想法、确认要求，再决定如何创作。'
              : '创作对话暂未开放，你仍可以使用拍摄提案表单。'}
          </p>
        </div>
        <div className="dp-journey">
          {[
            {
              icon: MessageCircle,
              title: '先听你说说',
              text: '一个场景、一种情绪，或者一句随口的想法。',
            },
            {
              icon: WandSparkles,
              title: '一起把画面想清楚',
              text: '整理想法、上传参考，形成可以修改的拍摄提案。',
            },
            {
              icon: Heart,
              title: '把喜欢的瞬间留下',
              text: '你确认后才开始创作，进度和作品都在同一个空间。',
            },
          ].map((step, index) => (
            <div className="dp-journey-step" key={step.title}>
              <span className="dp-journey-icon">
                <step.icon size={18} strokeWidth={1.4} />
              </span>
              <div>
                <small>0{index + 1}</small>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </div>
            </div>
          ))}
        </div>
        <span className="dp-companion-star" aria-hidden="true">
          ✧
        </span>
      </section>
      <footer className="dp-footer dp-width">
        <span>
          映序 <small>LUMIÈRE</small>
        </span>
        <p>愿每一次看见自己，都多一点喜欢。</p>
        <Link to="/projects">
          我的故事
          <ArrowUpRight size={12} />
        </Link>
      </footer>
      <span className="at-sr-only">{experience.photographer.title}</span>
    </>
  );
}

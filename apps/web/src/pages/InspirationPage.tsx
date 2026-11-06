/** 正式灵感套系：只展示服务端注册镜头，选片通过应用内存带入命名或现有项目。 */
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ArrowUpRight, Check, Images, Sparkles } from 'lucide-react';
import { useApp } from '../app/context';
import { LumiAvatar } from '../features/atelier/ui';
import { useCreationEntry } from '../features/atelier/useCreationEntry';

export default function InspirationPage() {
  const { catalog } = useApp();
  const [search] = useSearchParams();
  const styles = catalog.styles.filter(
    (style) => !search.get('kind') || style.kind === search.get('kind'),
  );
  const [styleId, setStyleId] = useState(search.get('style') ?? styles[0]?.id);
  const style = styles.find((item) => item.id === styleId) ?? styles[0];
  const [selection, setSelection] = useState<Record<string, string[]>>({});
  const selected = style
    ? (selection[style.id] ?? style.shots.slice(0, 1).map((shot) => shot.id))
    : [];
  const [use, setUse] = useState<'same' | 'mood'>('same');
  const start = useCreationEntry();
  const canTemplate = catalog.creation_modes.some((mode) => mode.id === 'template');
  const canPortrait = catalog.creation_modes.some((mode) => mode.id === 'portrait');
  const usage = !canTemplate && canPortrait ? 'mood' : use;
  if (!style)
    return (
      <div className="empty-state">
        <h1>新的灵感，正在准备。</h1>
        <p>当前没有可用套系，请稍后再来。</p>
      </div>
    );
  return (
    <section className="cx-library dp-width">
      <Link className="cx-back" to="/">
        <ArrowLeft size={14} /> 回到灵感首页
      </Link>
      <div className="cx-library-heading">
        <div>
          <span className="dp-eyebrow">A STORY YOU CAN STEP INTO</span>
          <h1>
            让喜欢的画面，<em>有你的模样。</em>
          </h1>
          <p>先选一种心情，再挑想走进的镜头。每张样片的用途，由你决定。</p>
        </div>
        <span className="cx-pill">
          <Images size={14} /> 灵感套系
        </span>
      </div>
      <div className="cx-mood-pills" aria-label="选择写真套系">
        {styles.map((item) => (
          <button
            key={item.id}
            aria-pressed={style.id === item.id}
            onClick={() => setStyleId(item.id)}
          >
            <img src={item.image} alt="" />
            {item.name}
          </button>
        ))}
      </div>
      <div className="cx-library-layout">
        <div className="cx-library-photos">
          <div className="cx-collection-title">
            <div>
              <span className="dp-eyebrow">A FEW MOMENTS TO FALL INTO</span>
              <h2>{style.name}</h2>
            </div>
            <span>
              {style.shots.length} 个镜头 · {style.kind === 'wedding' ? '双人故事' : '私人肖像'}
            </span>
          </div>
          <div className="cx-shot-grid" data-count={style.shots.length}>
            {style.shots.map((shot, index) => (
              <button
                className={'cx-shot ' + (selected.includes(shot.id) ? 'is-selected' : '')}
                key={shot.id}
                aria-label={'选择镜头 ' + (index + 1)}
                aria-pressed={selected.includes(shot.id)}
                onClick={() =>
                  setSelection((current) => ({
                    ...current,
                    [style.id]: selected.includes(shot.id)
                      ? selected.filter((id) => id !== shot.id)
                      : [...selected, shot.id],
                  }))
                }
              >
                <div>
                  <img
                    src={shot.image}
                    style={{ objectPosition: shot.position }}
                    alt={style.name + ' · ' + shot.name}
                  />
                  <span className="cx-shot-check">
                    {selected.includes(shot.id) ? (
                      <Check size={15} />
                    ) : (
                      String(index + 1).padStart(2, '0')
                    )}
                  </span>
                  <small>
                    {shot.development_only ? '内测样片' : '灵感样片'} · {shot.name}
                  </small>
                </div>
                <h3>{shot.name}</h3>
                <p>{style.mood}</p>
              </button>
            ))}
          </div>
          {!style.shots.length && (
            <p className="notice">
              当前套系还没有开放可作为输入的镜头。你可以从首页选择设计写真或文字创作。
            </p>
          )}
          <div className="cx-library-letter">
            <LumiAvatar small />
            <p>{style.description || '留下一两个心动镜头，我们从那里开始。'}</p>
            <span aria-hidden="true">✧</span>
          </div>
        </div>
        <aside className="cx-library-aside">
          <span className="dp-eyebrow">MAKE IT YOURS</span>
          <h2>想怎样走进这个故事？</h2>
          <button
            className={'cx-use-card ' + (usage === 'same' ? 'is-selected' : '')}
            disabled={!canTemplate}
            aria-pressed={usage === 'same'}
            onClick={() => setUse('same')}
          >
            <span>
              <Images size={18} />
              <strong>拍选中的同款</strong>
              {usage === 'same' && <Check size={15} />}
            </span>
            <p>每个镜头作为独立底图，使用你选定的人物参考。</p>
          </button>
          <button
            className={'cx-use-card ' + (usage === 'mood' ? 'is-selected' : '')}
            disabled={!canPortrait}
            aria-pressed={usage === 'mood'}
            onClick={() => setUse('mood')}
          >
            <span>
              <Sparkles size={18} />
              <strong>只借鉴这份氛围</strong>
              {usage === 'mood' && <Check size={15} />}
            </span>
            <p>作为风格参考，一起设计新的场景与构图。</p>
          </button>
          <div className="cx-selection-summary">
            <span>已经心动</span>
            <strong>
              {selected.length} <small>个镜头</small>
            </strong>
            <p>
              {usage === 'same'
                ? '每个镜头分别创作，共用人物参考。'
                : '所选镜头将计入风格参考输入限制。'}
            </p>
          </div>
          <button
            className="dp-primary"
            disabled={!selected.length || (!canTemplate && !canPortrait)}
            onClick={() =>
              start({
                brief: `我喜欢「${style.name}」，${usage === 'same' ? '想拍所选镜头的同款。' : '想借鉴氛围，设计自己的写真。'}`,
                styleId: style.id,
                mode: usage === 'same' ? 'template' : 'portrait',
                shotIds: usage === 'same' ? selected : [],
                styleShotIds: usage === 'mood' ? selected : [],
                projectId: search.get('project') ?? undefined,
              })
            }
          >
            带着灵感去工作室 <ArrowUpRight size={16} />
          </button>
          <p className="cx-fineprint">先整理提案，确认后才生成与预占次数。</p>
        </aside>
      </div>
    </section>
  );
}

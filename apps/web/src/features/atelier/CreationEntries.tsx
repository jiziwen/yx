/** 配置驱动的创作入口；图标和体验文案独立于供应商参数。 */
import { ArrowUpRight } from 'lucide-react';
import { useApp } from '../../app/context';
import { creationModes, type CreationMode } from './creationModes';

export default function CreationEntries({ onChoose }: { onChoose: (mode: CreationMode) => void }) {
  const { catalog } = useApp();
  return (
    <section className="cx-entry-section dp-width">
      <div className="cx-entry-heading">
        <span className="dp-eyebrow">EVERY STORY HAS ITS OWN BEGINNING</span>
        <h2>
          今天的创作，<em>想从哪里开始？</em>
        </h2>
        <p>有一张心动样片，有自己的照片，或者只有一个想法，都很好。</p>
      </div>
      <div className="cx-entry-grid">
        {creationModes
          .filter((mode) => catalog.creation_modes.some((item) => item.id === mode.id))
          .map((mode, index) => (
            <button className="cx-entry-card" key={mode.id} onClick={() => onChoose(mode.id)}>
              <span className="cx-entry-top">
                <mode.icon size={23} strokeWidth={1.3} />
                <small>0{index + 1}</small>
              </span>
              <h3>{mode.title}</h3>
              <p>{mode.description}</p>
              <span className="cx-entry-bottom">
                {mode.hint}
                <ArrowUpRight size={17} />
              </span>
            </button>
          ))}
      </div>
    </section>
  );
}

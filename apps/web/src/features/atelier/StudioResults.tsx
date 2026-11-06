/** 缩略图作品集、真实任务进度与原生大图弹框；素材仍逐次验证私有访问权限。 */
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { assetUrl, request } from '@yingxu/api-client';
import {
  ArrowUpRight,
  ArrowLeft,
  ArrowRight,
  Check,
  Clock3,
  Download,
  Heart,
  ImagePlus,
  LoaderCircle,
  X,
} from 'lucide-react';
import { useApp } from '../../app/context';
import { Status } from '../../shared/ui';
import QualityFeedback from './QualityFeedback';
import StudioDialog from './StudioDialog';
import { activeJobs, jobLabels, type StudioData } from './useStudioProject';

export default function StudioResults({
  projectId,
  data,
  visible,
  onEdit,
  onAnalyze,
  onDiscuss,
}: {
  projectId: string;
  data: StudioData;
  visible: boolean;
  onEdit?: (id: string) => void;
  onAnalyze?: (id: string) => void;
  onDiscuss?: (id: string) => void;
}) {
  const { notify } = useApp();
  const [selected, setSelected] = useState<string[]>([]);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const works = data.works.data ?? [];
  const jobs = data.jobs.data ?? [];
  const pending = jobs.filter((job) => activeJobs.has(job.status));
  const finished = jobs.filter((job) => job.status === 'succeeded');
  const unresolved = jobs.filter((job) => job.status === 'failed');
  const waitingForImages = finished.some(
    (job) => !works.some((asset) => asset.source_job_id === job.id),
  );
  const previewIndex = works.findIndex((asset) => asset.id === previewId);
  const preview = works[previewIndex];
  useEffect(() => {
    if (!visible) setPreviewId(null);
  }, [visible]);
  const cancel = useMutation({
    mutationFn: (id: string) => request(`/web/jobs/${id}/cancel`, { method: 'POST' }),
    onSuccess: data.refresh,
    onError: (error) => notify(error.message),
  });
  const toggleSelected = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  const actOnPreview = (action: (id: string) => void) => {
    if (!preview) return;
    const id = preview.id;
    setPreviewId(null);
    // 先解除原生弹框的背景隔离，再切换画布或聚焦聊天输入。
    requestAnimationFrame(() => action(id));
  };
  useEffect(() => {
    if (!preview) return;
    const navigate = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.matches('input, textarea, select') || target.isContentEditable)
      )
        return;
      const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
      const next = works[previewIndex + direction];
      if (direction && next) {
        event.preventDefault();
        setPreviewId(next.id);
      }
    };
    window.addEventListener('keydown', navigate);
    return () => window.removeEventListener('keydown', navigate);
  }, [previewId, works]);
  const taskRow = (job: (typeof jobs)[number]) => (
    <div key={job.id} className={`sx-task state-${job.status}`}>
      <span className="sx-task-icon">
        {job.status === 'succeeded' ? (
          <Check size={15} />
        ) : activeJobs.has(job.status) ? (
          <LoaderCircle size={15} className="spin" />
        ) : (
          <Clock3 size={15} />
        )}
      </span>
      <div>
        <strong>第 {job.item_index} 张</strong>
        <small>
          {job.status === 'reconciliation_required' &&
          [
            'PROVIDER_UNSAFE_RESULT',
            'PROVIDER_RESULT_UNAVAILABLE',
            'PROVIDER_RESULT_TOO_LARGE',
          ].includes(job.error_code ?? '')
            ? '正在获取生成结果'
            : (jobLabels[job.status] ?? job.status)}
        </small>
      </div>
      {['queued', 'running'].includes(job.status) && (
        <button
          className="icon-button"
          aria-label={`取消第${job.item_index}张`}
          disabled={cancel.isPending}
          onClick={() => cancel.mutate(job.id)}
        >
          <X size={14} />
        </button>
      )}
    </div>
  );
  return (
    <section className="sx-results" aria-label="生成进度与作品">
      <header className="sx-results-heading">
        <div>
          <h2>你的作品</h2>
          <p>
            {works.length} 张作品{pending.length ? ` · ${pending.length} 张处理中` : ''}
            {unresolved.length ? ` · ${unresolved.length} 张未完成` : ''}
          </p>
        </div>
        <Link to={`/projects/${projectId}/works`} aria-label="查看与下载全部作品">
          全部作品 <ArrowUpRight size={14} />
        </Link>
      </header>
      <Status
        loading={data.jobs.isLoading}
        error={data.jobs.error}
        retry={() => data.jobs.refetch()}
      >
        {!!pending.length && (
          <div className="sx-task-strip" aria-label="正在处理的任务">
            {pending.map(taskRow)}
          </div>
        )}
        {!!jobs.length && (
          <details className="sx-task-history">
            <summary>
              任务记录 · 已完成 {finished.length} / {jobs.length} 张
            </summary>
            <div className="sx-task-grid">{jobs.map(taskRow)}</div>
          </details>
        )}
        {!jobs.length && !works.length && (
          <div className="sx-results-empty">
            <ImagePlus size={28} />
            <p>这里，等待你的第一张作品。</p>
            <small>确认方案后，真实进度会出现在这里。</small>
          </div>
        )}
      </Status>
      {waitingForImages && data.works.isFetching && (
        <p className="sx-delivery-note" role="status">
          <LoaderCircle size={14} className="spin" />
          正在同步作品…
        </p>
      )}
      <Status
        loading={data.works.isLoading}
        error={data.works.error}
        retry={() => data.works.refetch()}
      >
        <div className="sx-work-grid">
          {works.map((asset, index) => (
            <article className="sx-work-card" key={asset.id}>
              <button
                className="sx-work-thumb"
                type="button"
                onClick={() => setPreviewId(asset.id)}
                aria-label={`查看作品${index + 1}大图`}
              >
                <img
                  src={assetUrl(asset.id)}
                  alt={asset.development_sample ? '开发测试卡片' : `已完成作品 ${index + 1}`}
                  loading="lazy"
                />
                <span className="sx-work-zoom">
                  查看大图 <ArrowUpRight size={13} />
                </span>
              </button>
              <div className="sx-work-meta">
                <strong>作品 {String(index + 1).padStart(2, '0')}</strong>
                <small>
                  {asset.width} × {asset.height}
                  {asset.development_sample ? ' · 测试卡片' : ''}
                </small>
              </div>
              <div className="sx-work-actions">
                <button
                  className="icon-button"
                  aria-label={`${selected.includes(asset.id) ? '取消喜欢' : '喜欢'}作品${index + 1}`}
                  aria-pressed={selected.includes(asset.id)}
                  onClick={() => toggleSelected(asset.id)}
                >
                  <Heart size={15} fill={selected.includes(asset.id) ? 'currentColor' : 'none'} />
                </button>
                <a
                  className="icon-button"
                  href={assetUrl(asset.id, true)}
                  aria-label={`下载作品${index + 1}`}
                >
                  <Download size={15} />
                </a>
                {onEdit && (
                  <button
                    className="sx-work-edit"
                    aria-label="以此为底图继续修改"
                    onClick={() => onEdit(asset.id)}
                  >
                    继续修改 <ArrowUpRight size={13} />
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
        {!!selected.length && (
          <p className="sx-selection-note">
            本次选中 {works.filter((asset) => selected.includes(asset.id)).length} 张 ·
            临时选择仅在当前页保留
          </p>
        )}
      </Status>
      {preview && (
        <StudioDialog
          title="作品预览"
          className="sx-work-preview"
          showFooter={false}
          onClose={() => setPreviewId(null)}
        >
          <div className="sx-preview-nav">
            <button
              className="icon-button"
              aria-label="上一张作品"
              disabled={previewIndex <= 0}
              onClick={() => setPreviewId(works[previewIndex - 1].id)}
            >
              <ArrowLeft size={18} />
            </button>
            <span>
              作品 {previewIndex + 1} / {works.length}{' '}
              <small>
                {preview.width} × {preview.height}
              </small>
            </span>
            <button
              className="icon-button"
              aria-label="下一张作品"
              disabled={previewIndex >= works.length - 1}
              onClick={() => setPreviewId(works[previewIndex + 1].id)}
            >
              <ArrowRight size={18} />
            </button>
          </div>
          <div className="sx-preview-image">
            <img src={assetUrl(preview.id)} alt={`作品大图 · 第${previewIndex + 1}张`} />
          </div>
          <div className="sx-preview-actions">
            <a className="sx-button" href={assetUrl(preview.id, true)}>
              <Download size={15} />
              下载原图
            </a>
            {onEdit && (
              <button className="sx-button sx-primary" onClick={() => actOnPreview(onEdit)}>
                以此为底图继续修改 <ArrowUpRight size={14} />
              </button>
            )}
            {onAnalyze && (
              <button className="sx-button" onClick={() => actOnPreview(onAnalyze)}>
                帮我看看这张
              </button>
            )}
            {onDiscuss && (
              <button className="sx-button" onClick={() => actOnPreview(onDiscuss)}>
                和 Lumi 聊这张
              </button>
            )}
          </div>
          <div className="sx-preview-feedback">
            <QualityFeedback
              key={preview.id}
              projectId={projectId}
              assetId={preview.id}
              assets={data.assets.data ?? []}
              refresh={data.refresh}
            />
          </div>
        </StudioDialog>
      )}
    </section>
  );
}

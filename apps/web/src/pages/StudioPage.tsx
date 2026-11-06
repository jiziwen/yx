/** 双入口工作室，共享私有草稿与冻结确认，明确点击才执行图片任务。 */
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  newKey,
  request,
  type Asset,
  type Plan,
  type AgentDraftPatch,
  type AgentConversation,
} from '@yingxu/api-client';
import { ArrowLeft, Gift, Images, SlidersHorizontal } from 'lucide-react';
import { RequireUser, useApp } from '../app/context';
import { Status } from '../shared/ui';
import StudioGuide, { sameDraft } from '../features/atelier/StudioGuide';
import ProposalChanges from '../features/atelier/ProposalChanges';
import StudioResults from '../features/atelier/StudioResults';
import StudioCreationPane, { type MaterialKind } from '../features/atelier/StudioCreationPane';
import useStudioDraft from '../features/atelier/useStudioDraft';
import {
  describeDraft,
  initialDraft,
  planBody,
  transitionDraft,
  type CreationDraft,
} from '../features/atelier/creationDraft';
import {
  activeJobs,
  useStudioProject,
  type StudioData,
} from '../features/atelier/useStudioProject';

export { jobLabels } from '../features/atelier/useStudioProject';
export default function StudioPage() {
  const { projectId = '' } = useParams();
  return (
    <RequireUser>
      <ProjectStudio key={projectId} projectId={projectId} />
    </RequireUser>
  );
}
function ProjectStudio({ projectId }: { projectId: string }) {
  const data = useStudioProject(projectId);
  const queries = [data.project, data.subjects, data.assets, data.plans];
  if (!data.project.data || !data.subjects.data || !data.assets.data || !data.plans.data)
    return (
      <Status
        loading={queries.some((query) => query.isLoading)}
        error={queries.find((query) => query.error)?.error}
        retry={data.refresh}
      />
    );
  return <StudioSession projectId={projectId} data={data} />;
}
function StudioSession({ projectId, data }: { projectId: string; data: StudioData }) {
  const { catalog, notify, creativeEntry, setCreativeEntry } = useApp();
  const client = useQueryClient();
  const project = data.project.data!;
  const subjects = data.subjects.data!;
  const assets = [
    ...data.assets.data!,
    ...(data.works.data ?? []).filter(
      (work) => !data.assets.data!.some((asset) => asset.id === work.id),
    ),
  ];
  const styles = catalog.styles.filter((style) => style.kind === project.kind);
  const latest = data.plans.data![0];
  const readonly = project.lifecycle !== 'active';
  const [initial] = useState(() =>
    initialDraft(
      styles,
      catalog,
      assets,
      latest,
      creativeEntry?.projectId === projectId ? creativeEntry : null,
    ),
  );
  useEffect(() => {
    if (creativeEntry?.projectId === projectId) setCreativeEntry(null);
  }, []);
  const local = useStudioDraft(projectId, project.privacy_epoch, initial, readonly);
  const { draft, setDraft } = local;
  const state = describeDraft(draft, catalog, assets, subjects);
  const [detailsHost, setDetailsHost] = useState<HTMLDivElement | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [materialRequest, setMaterialRequest] = useState<{ kind: MaterialKind; nonce: number }>();
  const [results, setResults] = useState(false);
  const [candidate, setCandidate] = useState<{
    patch: AgentDraftPatch;
    source: CreationDraft;
    runId: string;
    briefRevision: number;
    memoryRevision: number;
  } | null>(null);
  const [analysisTarget, setAnalysisTarget] = useState<{ id: string; nonce: number }>();
  const [prepared, setPrepared] = useState<{ stamp: string; plan: Plan } | null>(null);
  const [retry, setRetry] = useState(0);
  const attempted = useRef('');
  const pending = useRef<{ body: string; key: string } | null>(null);
  const update = (patch: Partial<CreationDraft>) =>
    setDraft((current) => transitionDraft(current, patch));
  const stamp = JSON.stringify([
    local.stored?.revision,
    project.brief_revision,
    project.privacy_epoch,
    draft,
    catalog.creation_modes,
    catalog.styles,
    catalog.creation_prompt_policy_hash,
  ]);
  const currentStamp = useRef(stamp);
  currentStamp.current = stamp;
  const saved = useMutation({
    mutationFn: async ({
      values,
      version,
      stamp: source,
    }: {
      values: CreationDraft;
      version: number;
      stamp: string;
    }) => {
      const body = JSON.stringify({
        ...planBody(
          values,
          describeDraft(values, catalog, assets, subjects),
          project.brief_revision,
        ),
        studio_draft_revision: version,
      });
      if (pending.current?.body !== body) pending.current = { body, key: newKey() };
      const plan = await request<Plan>(`/web/projects/${projectId}/plans`, {
        method: 'POST',
        headers: { 'Idempotency-Key': pending.current.key },
        body,
      });
      return { stamp: source, plan };
    },
    onSuccess: (value) => {
      pending.current = null;
      setPrepared(value);
      client.setQueryData<Plan[]>(['plans', projectId], (current) => [
        value.plan,
        ...(current ?? []).filter((plan) => plan.id !== value.plan.id),
      ]);
    },
    onError: () => data.refresh(),
  });
  // 冻结方案不消耗次数；每个稳定草稿只准备一次，失败由用户显式重试。
  useEffect(() => {
    if (readonly || !local.synced || !local.stored || state.issues.length || saved.isPending)
      return;
    const attempt = stamp + ':' + retry;
    if (attempted.current === attempt) return;
    if (
      !retry &&
      latest?.spec_json.prompt_policy_hash &&
      latest?.spec_json.prompt_policy_hash === catalog.creation_prompt_policy_hash &&
      latest.spec_json.studio_draft_revision === local.stored.revision &&
      latest.spec_json.style_version === state.style?.version &&
      latest.brief_revision === project.brief_revision &&
      new Date(latest.expires_at).getTime() > Date.now()
    ) {
      attempted.current = attempt;
      setPrepared({ stamp, plan: latest });
      return;
    }
    const timer = setTimeout(() => {
      attempted.current = attempt;
      saved.mutate({ values: draft, version: local.stored!.revision, stamp });
    }, 500);
    return () => clearTimeout(timer);
  }, [stamp, retry, local.synced, readonly, saved.isPending, state.issues.join('|')]);
  const grant = useMutation({
    mutationFn: () => request(`/web/projects/${projectId}/trial-grants`, { method: 'POST' }),
    onSuccess: () => {
      data.refresh();
      notify('试用权益已放入这个项目。');
    },
    onError: (error) => notify(error.message),
  });
  const onUploaded = (asset: Asset) => {
    client.setQueryData<Asset[]>(['assets', projectId], (current) => [
      ...(current ?? []).filter((item) => item.id !== asset.id),
      asset,
    ]);
    if (asset.kind === 'reference')
      setDraft((current) => ({
        ...current,
        reference_asset_ids: [...new Set([...current.reference_asset_ids, asset.id])],
      }));
    else if (asset.kind === 'style')
      setDraft((current) => ({
        ...current,
        style_asset_ids: [...new Set([...current.style_asset_ids, asset.id])],
      }));
    else update({ base_asset_id: asset.id });
    data.refresh();
  };
  const upload = useMutation({
    mutationFn: ({ file, purpose }: { file: File; purpose: 'base' | 'style' }) => {
      if (file.size > catalog.upload_limits.max_bytes) throw new Error('底图超过上传大小限制');
      const body = new FormData();
      body.set('file', file);
      body.set('purpose', purpose);
      body.set('declared', 'true');
      return request<Asset>(`/web/projects/${projectId}/uploads`, { method: 'POST', body });
    },
    onSuccess: onUploaded,
    onError: (error) => notify(error.message),
  });
  const plan = prepared?.plan;
  const blocked =
    local.error?.message ||
    saved.error?.message ||
    state.issues[0] ||
    (!local.synced
      ? '正在保存当前想法…'
      : saved.isPending
        ? '正在准备确认卡…'
        : !plan || prepared?.stamp !== stamp
          ? '正在准备当前方案…'
          : (data.account.data?.available ?? 0) < plan.quota_snapshot.photo
            ? '可用次数不足，请先领取试用或补充次数。'
            : '');
  const canConfirm =
    !!plan &&
    prepared.stamp === stamp &&
    local.synced &&
    !local.error &&
    !readonly &&
    !state.issues.length &&
    !saved.isPending &&
    !upload.isPending &&
    plan.approval_status === 'pending' &&
    (data.account.data?.available ?? 0) >= plan.quota_snapshot.photo &&
    (!latest || latest.id === plan.id);
  const accept = useMutation({
    mutationFn: () => {
      if (!canConfirm || !plan || currentStamp.current !== prepared?.stamp)
        throw new Error('当前要求已变化，请等待新确认卡。');
      return request(`/web/approvals/${plan.approval_id}/accept`, {
        method: 'POST',
        headers: { 'Idempotency-Key': `studio-${plan.approval_id}` },
      });
    },
    onSuccess: () => {
      setPrepared((current) =>
        current ? { ...current, plan: { ...current.plan, approval_status: 'accepted' } } : null,
      );
      data.refresh();
      setResults(true);
      notify('方案已确认，创作任务已排队。');
    },
    onError: () => data.refresh(),
  });
  const locked = readonly || accept.isPending || upload.isPending || !local.stored;
  const running = data.jobs.data?.some((job) => activeJobs.has(job.status));
  const onEdit = (id: string) => {
    if (locked) return;
    update({ mode: 'edit', base_asset_id: id, change: '光线更柔和，保留其他细节' });
    setResults(false);
  };
  const applyProposal = (value: AgentDraftPatch) => {
    if (locked) return false;
    update(
      Object.fromEntries(
        Object.entries(value).filter(([key, field]) => key !== 'intent' && field != null),
      ) as Partial<CreationDraft>,
    );
    setCandidate(null);
    setResults(false);
    notify('创意已同步到画布，确认后才会生成。');
    return true;
  };
  const confirmation = (
    <button
      className="sx-button sx-primary sx-generate"
      disabled={!canConfirm || accept.isPending}
      onClick={() => accept.mutate()}
    >
      {accept.isPending
        ? '正在确认…'
        : plan?.approval_status === 'accepted' && prepared?.stamp === stamp
          ? '已确认执行'
          : `确认生成 ${state.count} 张`}
    </button>
  );
  const resultPane = (
    <StudioResults
      projectId={projectId}
      data={data}
      visible={results}
      onAnalyze={(id) => {
        setAnalysisTarget({ id, nonce: Date.now() });
        setShowDetails(true);
      }}
      onDiscuss={(id) => {
        onEdit(id);
        document.querySelector<HTMLTextAreaElement>('[aria-label="给 Lumi 留言"]')?.focus();
      }}
      onEdit={
        !locked && catalog.creation_modes.some((mode) => mode.id === 'edit') ? onEdit : undefined
      }
    />
  );
  if (!local.stored) return <Status loading error={local.error} retry={local.reload} />;
  return (
    <section className="sx-studio">
      <header className="sx-header">
        <Link className="sx-project-back" to="/projects" aria-label="返回我的项目">
          <ArrowLeft size={16} />
        </Link>
        <h1>{project.title}</h1>
        <small>
          {readonly
            ? '项目已归档'
            : running
              ? '有任务正在处理'
              : local.synced
                ? '想法已保存'
                : '保存中…'}
        </small>
        <Link to={`/projects/${projectId}/works`} className="sx-works-link">
          <Images size={15} />
          作品
        </Link>
        <span className="sx-balance">{data.account.data?.available ?? 0} 次可用</span>
      </header>
      <div className="sx-main">
        <StudioGuide
          projectId={projectId}
          revision={project.brief_revision}
          privacyEpoch={project.privacy_epoch}
          draft={draft}
          assets={assets}
          detailsHost={detailsHost}
          analysisTarget={analysisTarget}
          enabled={catalog.features.chat_enabled ?? false}
          readonly={locked}
          onApply={applyProposal}
          onAttach={() => {
            setResults(false);
            setMaterialRequest({ kind: 'attachments', nonce: Date.now() });
          }}
          onProposal={(value) =>
            setCandidate((current) => (current?.runId === value?.runId ? current : value))
          }
        />
        <div className="sx-workspace cx-canvas" aria-label="操作与画布">
          <div className="sx-workspace-nav">
            <div className="sx-view-tabs">
              <button
                aria-pressed={!results}
                aria-controls="studio-creation-view"
                onClick={() => setResults(false)}
              >
                创作画面
              </button>
              <button
                aria-pressed={results}
                aria-controls="studio-results-view"
                onClick={() => setResults(true)}
              >
                作品与进度{running && <i />}
              </button>
            </div>
            <button
              className="sx-memory-trigger"
              aria-expanded={showDetails}
              onClick={() => setShowDetails((value) => !value)}
            >
              <SlidersHorizontal size={14} />
              记忆与分析
            </button>
          </div>
          <section id="studio-creation-view" aria-label="创作画面" hidden={results}>
            {candidate && (
              <section className="sx-suggestion" aria-label="摄影师建议">
                <strong>Lumi 的建议</strong>
                <ProposalChanges
                  proposal={candidate.patch}
                  original={candidate.source}
                  styles={styles}
                />
                {!sameDraft(candidate.source, draft) && <p>草稿已有新修改，请重新整理建议。</p>}
                <div>
                  <button
                    className="sx-button"
                    disabled={locked || !sameDraft(candidate.source, draft)}
                    onClick={() => {
                      const conversation = client.getQueryData<AgentConversation>([
                        'conversation',
                        projectId,
                        project.privacy_epoch,
                      ]);
                      if (
                        candidate.briefRevision !== project.brief_revision ||
                        candidate.memoryRevision !== conversation?.memory.revision ||
                        !sameDraft(candidate.source, draft)
                      ) {
                        setCandidate(null);
                        notify('建议已过期，请基于当前要求重新整理。');
                        return;
                      }
                      if (applyProposal(candidate.patch)) setResults(false);
                    }}
                  >
                    采用这个建议
                  </button>
                  <button className="sx-text-button" onClick={() => setCandidate(null)}>
                    暂不采用
                  </button>
                </div>
              </section>
            )}
            <StudioCreationPane
              projectId={projectId}
              kind={project.kind}
              draft={draft}
              catalog={catalog}
              assets={assets}
              subjects={subjects}
              readonly={locked}
              onChange={update}
              onUpload={(file, purpose) => upload.mutate({ file, purpose })}
              onUploaded={onUploaded}
              refresh={data.refresh}
              confirmation={confirmation}
              materialRequest={materialRequest}
            />
            <div
              className="sx-studio-status"
              role={local.error || saved.error || accept.error ? 'alert' : 'status'}
            >
              <p>
                {local.error?.message ||
                  accept.error?.message ||
                  blocked ||
                  (plan?.approval_status === 'accepted'
                    ? '本方案已确认，请查看作品与进度。'
                    : `确认后生成 ${state.count} 张，消耗 ${plan?.quota_snapshot.photo ?? state.count} 次。`)}
              </p>
              {state.capability?.development_sample && <small>当前图片通道为开发测试卡片。</small>}
              {local.error && (
                <div>
                  <button
                    onClick={() => {
                      if (window.confirm('载入最新草稿会替换当前编辑，是否继续？'))
                        void local.reload();
                    }}
                  >
                    载入最新草稿
                  </button>
                  <button onClick={local.retry}>重试保存</button>
                </div>
              )}
              {(saved.error || accept.error) && (
                <button
                  onClick={() => {
                    saved.reset();
                    accept.reset();
                    pending.current = null;
                    setRetry((value) => value + 1);
                  }}
                >
                  重新检查方案
                </button>
              )}
              {(data.account.data?.available ?? 0) === 0 && catalog.features.trial_enabled && (
                <button disabled={readonly || grant.isPending} onClick={() => grant.mutate()}>
                  <Gift size={13} />
                  领取 {catalog.trial_photo_count} 次内测试用
                </button>
              )}
            </div>
          </section>
          <div id="studio-results-view" hidden={!results}>
            {resultPane}
          </div>
        </div>
      </div>
      {showDetails && (
        <section className="sx-memory-panel" aria-label="创作记忆与分析">
          <div ref={setDetailsHost} />
        </section>
      )}
    </section>
  );
}

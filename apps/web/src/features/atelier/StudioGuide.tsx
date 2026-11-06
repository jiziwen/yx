/** 持久化创作 Agent：只提交对话、展示追问和提案，生成始终走独立确认入口。 */
import { createPortal } from 'react-dom';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowUp, Paperclip, LoaderCircle, RotateCcw } from 'lucide-react';
import {
  api,
  request,
  assetUrl,
  type Asset,
  ApiError,
  expectData,
  newKey,
  type AgentDraftPatch,
  type AgentMessageInput,
  type AgentRun,
  type AgentConversation,
  type ProjectMemory,
} from '@yingxu/api-client';
import { experience } from '../../config/experience';
import type { CreationDraft } from './creationDraft';
import { LumiAvatar } from './ui';
import { ProjectMemoryPanel, MemorySuggestion, BriefSuggestion } from './ProjectMemory';
import ToolObservations from './ToolObservations';
import { useApp } from '../../app/context';
import Citations from '../conversations/Citations';
import RunSteps from '../conversations/RunSteps';
import useConversationStream from './useConversationStream';
import useConversationHistory from './useConversationHistory';

const stages: Record<string, string> = {
  queued: '正在等待摄影师',
  reading_context: '正在查看当前草稿与素材信息',
  understanding: '正在理解你的想法',
  repairing: '正在校正提案格式',
  validating: '正在核对提案与模型能力',
  querying_tools: '正在查询项目次数与任务记录',
  reading_results: '正在根据查询结果整理回复',
  responding: '正在回复你',
};
const errors: Record<string, string> = {
  AGENT_TIMEOUT: '这次整理超时了。输入已保存，可以重新发送。',
  AGENT_CHANNEL_BUSY: '模型通道正忙，请稍后重新发送。',
  PROVIDER_RATE_LIMITED: '模型暂时限流，请稍后重试。',
  PROVIDER_AUTH_FAILED:
    '对话模型的供应商凭证无效或已过期，请检查后台凭证配置。输入已保留，更新后再发送。',
  PROVIDER_BALANCE_INSUFFICIENT: '对话模型的供应商账户余额不足，请处理后再发送。输入已保留。',
  PROVIDER_PERMISSION_DENIED: '供应商未授予这个对话模型的访问权限，请检查后台模型配置。',
  PROVIDER_MODEL_UNAVAILABLE: '这个对话模型或接口暂不可用，请检查后台模型配置。',
  PROVIDER_INVALID_REQUEST: '对话模型不接受当前请求参数，请检查后台模型接口配置。',
  PROVIDER_REJECTED: '供应商拒绝了这次对话请求，输入已保留。请检查后台模型配置后再发送。',
  PROVIDER_RESULT_UNKNOWN: '这次模型调用未能确认结果，尚未生成提案。可以稍后手动重试。',
  AGENT_INVALID_OUTPUT: '模型回复未通过提案校验，请重新整理，或继续使用右侧表单。',
  REVISION_CONFLICT: '项目资料已变化，请基于最新素材重新整理。',
  AUTHORIZATION_CHANGED: '素材授权已变化，请检查素材后重新发送。',
  PROVIDER_CONFIG_CHANGED: '模型或能力配置已变化，请重新整理。',
  CATALOG_CHANGED: '主题素材或用途已更新，请基于右侧最新配置重新发送。',
  AGENT_RELEASE_CHANGED: '摄影师配置已更新，请基于当前项目重新发送。',
  MEMORY_CHANGED: '项目记忆已更新，请基于你确认后的要求重新整理。',
  MEMORY_DISABLED: '项目记忆当前已停用，请重新整理。',
  MEMORY_CONFIG_CHANGED: '需求卡配置已更新，请重新查看后整理。',
  AGENT_TOOL_BUDGET_EXCEEDED: '这次查询已达到预算，请拆分问题后重新发送。',
  AGENT_CONTEXT_LIMIT: '这次上下文较长，请整理项目要求或指定具体任务后重试。',
};
/** 比较完整草稿，防止迟到的建议覆盖等待期间的新修改；对象键次序不影响比较。 */
export function sameDraft(left: unknown, right: unknown): boolean {
  const stable = (value: unknown): unknown =>
    Array.isArray(value)
      ? value.map(stable)
      : value && typeof value === 'object'
        ? Object.fromEntries(
            Object.entries(value)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([key, item]) => [key, stable(item)]),
          )
        : value;
  return JSON.stringify(stable(left)) === JSON.stringify(stable(right));
}

export default function StudioGuide({
  projectId,
  revision,
  privacyEpoch,
  draft,
  readonly,
  enabled,
  onApply,
  onProposal,
  assets = [],
  analysisTarget,
  detailsHost,
  onAttach,
}: {
  projectId: string;
  revision: number;
  privacyEpoch: number;
  draft: CreationDraft;
  readonly: boolean;
  enabled: boolean;
  onApply: (patch: AgentDraftPatch) => boolean;
  onProposal: (
    value: {
      patch: AgentDraftPatch;
      source: CreationDraft;
      runId: string;
      briefRevision: number;
      memoryRevision: number;
    } | null,
  ) => void;
  assets?: Asset[];
  analysisTarget?: { id: string; nonce: number };
  detailsHost: HTMLElement | null;
  onAttach: () => void;
}) {
  const { catalog } = useApp();
  const client = useQueryClient();
  const key = ['conversation', projectId, privacyEpoch];
  const [input, setInput] = useState('');
  const [analysisIds, setAnalysisIds] = useState<string[]>([]);
  const [analysisConsent, setAnalysisConsent] = useState(false);
  const [analysisShots, setAnalysisShots] = useState<string[]>([]);
  const analysisCount = analysisIds.length + analysisShots.length;
  useEffect(() => {
    if (analysisTarget) {
      setAnalysisIds([analysisTarget.id]);
      setAnalysisShots([]);
      setAnalysisConsent(false);
      setInput('帮我看看这张作品的光线、构图，给出可以修改的建议。');
    }
  }, [analysisTarget]);
  useEffect(() => {
    setAnalysisShots([]);
    setAnalysisConsent(false);
  }, [draft.style_id]);
  const vision = useQuery({
    queryKey: ['vision-capability'],
    queryFn: () =>
      request<{ enabled: boolean; model: string; max_input_images: number }>(
        '/web/vision-capability',
      ),
  });
  const [applied, setApplied] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState<AgentRun | null>(null);
  const pending = useRef<AgentMessageInput | null>(null);
  const generation = useRef(0);
  const log = useRef<HTMLDivElement>(null);
  const historyAnchor = useRef<{ height: number; top: number } | null>(null);
  const [accessRevoked, setAccessRevoked] = useState(false);
  const [resetting, setResetting] = useState(false);
  const clearConversation = () => {
    generation.current += 1;
    setSubmitted(null);
    setApplied([]);
    setInput('');
    setAnalysisIds([]);
    setAnalysisShots([]);
    setAnalysisConsent(false);
    pending.current = null;
    client.removeQueries({ queryKey: ['conversation', projectId] });
  };
  const connection = useConversationStream({
    projectId,
    privacyEpoch,
    enabled: enabled && !accessRevoked,
    onSync: () => client.invalidateQueries({ queryKey: key }),
    onReset: () => {
      setResetting(true);
      clearConversation();
      for (const resource of ['project', 'assets', 'subjects', 'works'])
        client.invalidateQueries({ queryKey: [resource, projectId] });
    },
    onRevoked: () => {
      clearConversation();
      setAccessRevoked(true);
      client.invalidateQueries({ queryKey: ['me'] });
      client.invalidateQueries({ queryKey: ['project', projectId] });
    },
  });
  const query = useQuery({
    queryKey: key,
    enabled: enabled && !accessRevoked,
    queryFn: async () =>
      expectData(
        await api.GET('/api/v1/web/projects/{project_id}/conversation', {
          params: { path: { project_id: projectId } },
        }),
      ),
    refetchInterval: (value) => {
      if (accessRevoked) return false;
      const active = value.state.data?.runs.some((run) =>
        ['queued', 'running'].includes(run.status),
      );
      if (connection.state === 'live') return active ? 15000 : 60000;
      return active ? Math.min(15000, 2000 * 2 ** Math.min(connection.failures, 3)) : 30000;
    },
    refetchOnWindowFocus: 'always',
    refetchOnReconnect: 'always',
    retry: (count, error) =>
      !(error instanceof ApiError && [401, 403, 404].includes(error.status)) && count < 2,
  });
  const history = useConversationHistory(
    projectId,
    privacyEpoch,
    query.data,
    !accessRevoked && !resetting,
  );
  const conversation = history.conversation;
  useEffect(() => {
    if (query.error instanceof ApiError && [401, 403, 404].includes(query.error.status)) {
      clearConversation();
      setAccessRevoked(true);
    }
  }, [query.error]);
  useEffect(() => {
    if (conversation && conversation.privacy_epoch !== privacyEpoch) {
      for (const resource of ['project', 'assets', 'subjects', 'works'])
        client.invalidateQueries({ queryKey: [resource, projectId] });
    }
  }, [conversation?.privacy_epoch, privacyEpoch, projectId, client]);
  const latest = conversation?.runs.at(-1);
  const active = [
    ...(conversation?.runs ?? []),
    ...(submitted && !conversation?.runs.some((r) => r.id === submitted.id) ? [submitted] : []),
  ].find((run) => ['queued', 'running'].includes(run.status));
  const refresh = () => client.invalidateQueries({ queryKey: key });
  const memorySaved = (memory: ProjectMemory) => {
    client.setQueryData<AgentConversation>(key, (current) =>
      current ? { ...current, memory } : current,
    );
    refresh();
  };
  const send = useMutation({
    onMutate: () => generation.current,
    mutationFn: async (body: AgentMessageInput) =>
      expectData(
        await api.POST('/api/v1/web/projects/{project_id}/messages', {
          params: { path: { project_id: projectId } },
          body,
        }),
      ),
    onSuccess: (run, _body, submittedGeneration) => {
      if (submittedGeneration !== generation.current) return;
      setSubmitted(run);
      setInput('');
      setAnalysisIds([]);
      setAnalysisShots([]);
      setAnalysisConsent(false);
      pending.current = null;
      refresh();
    },
    onError: (_error, _body, submittedGeneration) => {
      if (submittedGeneration !== generation.current) return;
      refresh();
      client.invalidateQueries({ queryKey: ['project', projectId] });
    },
  });
  const cancel = useMutation({
    onMutate: () => generation.current,
    mutationFn: async (id: string) =>
      expectData(
        await api.POST('/api/v1/web/agent-runs/{run_id}/cancel', {
          params: { path: { run_id: id } },
        }),
      ),
    onSuccess: (run, _id, submittedGeneration) => {
      if (submittedGeneration !== generation.current) return;
      setSubmitted(run);
      refresh();
    },
  });
  useEffect(() => {
    generation.current += 1;
    setSubmitted(null);
    setApplied([]);
    setInput('');
    setAnalysisIds([]);
    setAnalysisShots([]);
    setAnalysisConsent(false);
    pending.current = null;
    setResetting(false);
  }, [privacyEpoch]);
  useEffect(() => {
    if (historyAnchor.current) {
      if (!history.isPending && log.current) {
        log.current.scrollTop =
          historyAnchor.current.top + log.current.scrollHeight - historyAnchor.current.height;
        historyAnchor.current = null;
      }
      return;
    }
    if (!conversation?.messages.length || document.activeElement?.closest('.cx-creation-pane'))
      return;
    log.current?.scrollTo({
      top: log.current.scrollHeight,
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
  }, [conversation?.messages.length, active?.stage, send.error, history.isPending]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (
      !input.trim() ||
      readonly ||
      active ||
      send.isPending ||
      !enabled ||
      !conversation?.enabled ||
      (analysisCount > 0 && !analysisConsent)
    )
      return;
    const value = {
      text: input.trim(),
      draft,
      expected_revision: revision,
      expected_memory_revision: conversation.memory.revision,
      analysis_asset_ids: analysisIds,
      analysis_shots: analysisShots.map((shot_id) => ({ style_id: draft.style_id, shot_id })),
      analysis_consent: analysisConsent,
      analysis_purpose: analysisCount ? input.trim().slice(0, 200) : '',
    };
    if (!pending.current || !sameDraft({ ...pending.current, client_message_id: undefined }, value))
      pending.current = { ...value, client_message_id: newKey() };
    send.mutate(pending.current);
  };
  const busy = !!active || send.isPending;
  const partial = active
    ? connection.previews[active.id]?.preview === undefined
      ? active.reply_preview
      : connection.previews[active.id].preview
    : null;
  const visiblePartial =
    !accessRevoked && !resetting && partial && partial.attempt_no >= (active?.calls ?? 0)
      ? partial
      : null;
  useEffect(() => {
    if (document.activeElement?.closest('.cx-creation-pane')) return;
    log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'instant' });
  }, [visiblePartial?.text]);
  useEffect(() => {
    if (!submitted || readonly) return;
    const message = conversation?.messages.find(
      (item) => item.run_id === submitted.id && item.role === 'assistant',
    );
    const run = conversation?.runs.find((item) => item.id === submitted.id);
    if (
      !message?.proposal_json ||
      message.proposal_json.intent !== 'user_request' ||
      applied.includes(submitted.id) ||
      run?.status !== 'succeeded' ||
      run.brief_revision !== revision ||
      run.memory_revision !== conversation?.memory.revision ||
      !sameDraft(run.draft_context, draft)
    )
      return;
    if (onApply(message.proposal_json)) setApplied((items) => [...items, submitted.id]);
  }, [conversation, submitted, readonly, draft, revision, applied]);
  useEffect(() => {
    onProposal(null);
  }, [privacyEpoch, revision, conversation?.memory.revision, accessRevoked]);
  useEffect(() => {
    if (accessRevoked || resetting || readonly) return;
    const run = submitted
      ? conversation?.runs.find((item) => item.id === submitted.id)
      : conversation?.runs.find(
          (item) => item.status === 'succeeded' && sameDraft(item.draft_context, draft),
        );
    const message = conversation?.messages.find(
      (item) => item.run_id === run?.id && item.role === 'assistant',
    );
    if (
      run?.status === 'succeeded' &&
      run.brief_revision === revision &&
      run.memory_revision === conversation?.memory.revision &&
      run.draft_context &&
      message?.proposal_json &&
      !applied.includes(run.id) &&
      sameDraft(run.draft_context, draft) &&
      !(message.proposal_json.intent === 'user_request')
    )
      onProposal({
        patch: message.proposal_json,
        source: run.draft_context as CreationDraft,
        runId: run.id,
        briefRevision: run.brief_revision,
        memoryRevision: run.memory_revision,
      });
  }, [conversation, submitted, applied]);
  const failed = latest?.status === 'failed' || latest?.status === 'cancelled';
  const lastUser = conversation?.messages.filter((m) => m.role === 'user').at(-1);
  const details = (
    <>
      <p className="cx-fineprint">
        {conversation ? `对话模型 · ${conversation.model}` : '正在连接摄影师'}
      </p>
      {conversation?.memory && (
        <ProjectMemoryPanel
          projectId={projectId}
          memory={conversation.memory}
          readonly={readonly}
          onSaved={memorySaved}
        />
      )}
      {latest && <RunSteps run={latest} />}
      {conversation?.messages.map((message) => {
        const run = conversation.runs.find((item) => item.id === message.run_id);
        return (
          <div key={message.id}>
            {message.observations_json && (
              <ToolObservations observations={message.observations_json} />
            )}
            <Citations messageId={message.id} references={message.citations_json} />
            {message.memory_suggestion_json && (
              <MemorySuggestion
                projectId={projectId}
                memory={conversation.memory}
                runId={message.run_id}
                sourceRevision={run?.memory_revision}
                suggestions={message.memory_suggestion_json}
                readonly={readonly}
                onSaved={memorySaved}
              />
            )}
            {message.brief_suggestion_json && (
              <BriefSuggestion
                projectId={projectId}
                memory={conversation.memory}
                runId={message.run_id}
                sourceRevision={run?.memory_revision}
                patch={message.brief_suggestion_json}
                readonly={readonly}
                onSaved={memorySaved}
              />
            )}
            {!!run?.analysis_sources?.length && (
              <small>
                看图来源：
                {run.analysis_sources
                  .map(
                    (source) => String(source.kind) + ' · ' + String(source.asset_id).slice(0, 8),
                  )
                  .join('、')}
                ，仅针对当时版本。
              </small>
            )}
          </div>
        );
      })}
      <details className="cx-vision-picker" open={!!analysisTarget}>
        <summary>帮我看看 · 选择本轮分析的图片</summary>
        {!vision.data?.enabled ? (
          <p>视觉分析尚未配置启用；你仍可手动创作或讨论文字需求。</p>
        ) : (
          <>
            <p>
              本次由 {vision.data.model} 分析。最多 {vision.data.max_input_images}{' '}
              张，只发送勾选的图片。
            </p>
            <div className="cx-confirm-inputs">
              {assets.map((asset) => (
                <label key={asset.id}>
                  <img
                    width={64}
                    height={80}
                    style={{ objectFit: 'cover', borderRadius: 12 }}
                    src={assetUrl(asset.id)}
                    alt={asset.kind === 'reference' ? '可选人物参考' : '可选底图或作品'}
                  />
                  <input
                    type="checkbox"
                    checked={analysisIds.includes(asset.id)}
                    disabled={
                      busy ||
                      readonly ||
                      (!analysisIds.includes(asset.id) &&
                        analysisCount >= vision.data!.max_input_images)
                    }
                    onChange={(event) => {
                      setAnalysisConsent(false);
                      setAnalysisIds((current) =>
                        event.target.checked
                          ? [...current, asset.id]
                          : current.filter((id) => id !== asset.id),
                      );
                    }}
                  />
                  {asset.kind === 'reference'
                    ? '人物参考'
                    : asset.kind === 'photo'
                      ? '成片'
                      : '底图'}
                </label>
              ))}
            </div>
            <div className="cx-confirm-inputs">
              {catalog.styles
                .find((style) => style.id === draft.style_id)
                ?.shots.map((shot) => (
                  <label key={shot.id}>
                    <img width={64} height={80} src={shot.image} alt={shot.name} />
                    <input
                      type="checkbox"
                      checked={analysisShots.includes(shot.id)}
                      disabled={
                        busy ||
                        readonly ||
                        (!analysisShots.includes(shot.id) &&
                          analysisCount >= vision.data!.max_input_images)
                      }
                      onChange={(event) => {
                        setAnalysisConsent(false);
                        setAnalysisShots((current) =>
                          event.target.checked
                            ? [...current, shot.id]
                            : current.filter((id) => id !== shot.id),
                        );
                      }}
                    />
                    主题样片 · {shot.name}
                  </label>
                ))}
            </div>
            {!!analysisCount && (
              <label>
                <input
                  type="checkbox"
                  checked={analysisConsent}
                  onChange={(event) => setAnalysisConsent(event.target.checked)}
                />
                同意将以上 {analysisCount} 张图片发送给配置的视觉供应商，按输入框中的用途分析。
              </label>
            )}
          </>
        )}
      </details>
      {!!analysisCount && (
        <form onSubmit={submit}>
          <label>
            本次分析用途
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              maxLength={200}
            />
          </label>
          <button type="submit" disabled={!analysisConsent || busy || readonly || !input.trim()}>
            发送本次分析
          </button>
        </form>
      )}
    </>
  );
  return (
    <>
      <aside className="dp-chat" data-connection={connection.state}>
        <div className="dp-chat-heading">
          <LumiAvatar />
          <div>
            <h2>
              {experience.photographer.name}
              <span>AI</span>
            </h2>
            <p>聊想法，也能切换创作方式。</p>
          </div>
        </div>
        <div
          className="dp-chat-log"
          ref={log}
          role="log"
          aria-label="摄影师创作引导"
          aria-live="polite"
          aria-relevant="additions text"
        >
          {conversation?.older_cursor && (
            <button
              className="at-history-more"
              disabled={history.isPending}
              onClick={async () => {
                if (log.current)
                  historyAnchor.current = {
                    height: log.current.scrollHeight,
                    top: log.current.scrollTop,
                  };
                try {
                  await history.loadOlder();
                } catch {
                  historyAnchor.current = null;
                }
              }}
            >
              {history.isPending ? '正在找回更早的对话…' : '查看更早的对话'}
            </button>
          )}
          {history.error && (
            <p className="at-agent-error" role="alert">
              {history.error.message}
            </p>
          )}
          {!conversation?.messages.length && (
            <div className="dp-message dp-message-lumi">
              <span className="dp-message-star" aria-hidden="true">
                ✧
              </span>
              <div>
                <small>LUMI</small>
                <p>把想拍的画面告诉我，也可以直接说“拍同款”“设计写真”“修改照片”或“文字创作”。</p>
              </div>
            </div>
          )}
          {conversation?.messages.map((message) => (
            <div
              key={message.id}
              className={'dp-message dp-message-' + (message.role === 'assistant' ? 'lumi' : 'you')}
            >
              {message.role === 'assistant' && (
                <span className="dp-message-star" aria-hidden="true">
                  ✧
                </span>
              )}
              <div>
                <small>
                  {message.role === 'assistant' ? experience.photographer.name.toUpperCase() : '你'}
                </small>
                <p className="at-agent-text">{message.text}</p>
              </div>
            </div>
          ))}
          {visiblePartial?.text && (
            <div
              className="dp-message dp-message-lumi at-stream-reply"
              aria-label="Lumi 正在回复"
              aria-live="off"
            >
              <span className="dp-message-star" aria-hidden="true">
                ✧
              </span>
              <div>
                <small>{experience.photographer.name.toUpperCase()} · 正在回复</small>
                <p className="at-agent-text">
                  {visiblePartial.text}
                  <span className="at-stream-caret" aria-hidden="true" />
                </p>
              </div>
            </div>
          )}
          {busy && (
            <div className="at-agent-state" role="status">
              <LoaderCircle size={14} className="at-agent-spinner" />
              <span>{active ? (stages[active.stage] ?? '正在整理你的想法') : '正在发送需求'}</span>
              {active && (
                <button disabled={cancel.isPending} onClick={() => cancel.mutate(active.id)}>
                  停止
                </button>
              )}
            </div>
          )}
          {failed && !busy && (
            <div className="at-agent-error" role="status">
              <p>
                {latest.status === 'cancelled'
                  ? '这次整理已停止，你可以继续补充想法。'
                  : (errors[latest.error_code ?? ''] ??
                    '摄影师暂时未能完成回复，输入已保留，可以重试或编辑提案表单。')}
              </p>
              <button disabled={readonly} onClick={() => setInput(lastUser?.text ?? '')}>
                <RotateCcw size={12} />
                重新编辑这条需求
              </button>
            </div>
          )}
          {query.error && (
            <div className="at-agent-error" role="alert">
              {query.error.message}
              <button onClick={() => query.refetch()}>重新连接</button>
            </div>
          )}
          {(send.error || cancel.error) && (
            <p className="at-agent-error" role="alert">
              {(send.error ?? cancel.error)?.message}
            </p>
          )}
        </div>
        <form className="dp-composer" onSubmit={submit}>
          <textarea
            aria-label={`给 ${experience.photographer.name} 留言`}
            placeholder="想换模式、改背景、找灵感，都可以说…"
            maxLength={Math.min(experience.guide.maxMessageLength, 1200)}
            rows={2}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={readonly || busy || accessRevoked || !enabled || !conversation?.enabled}
          />
          <div>
            <button
              type="button"
              className="sx-attach"
              onClick={onAttach}
              disabled={readonly || busy}
            >
              <Paperclip size={14} />
              添加照片
            </button>
            <button
              className="dp-send"
              type="submit"
              aria-label={`发送给 ${experience.photographer.name}`}
              disabled={readonly || busy || !enabled || !input.trim() || !conversation?.enabled}
            >
              <ArrowUp size={18} />
            </button>
          </div>
        </form>
        <p className="dp-chat-footnote">聊完改好，确认后才生成。</p>
      </aside>
      {detailsHost && createPortal(details, detailsHost)}
    </>
  );
}

/** 公开诊断步骤仅显示真实调用和状态；没有隐藏推理内容。 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, expectData, type AgentRun } from '@yingxu/api-client';
const statuses: Record<string, string> = {
  running: '进行中',
  succeeded: '已完成',
  failed: '未完成',
  cancelled: '已停止',
};
const kinds: Record<string, string> = {
  routing: '角色选择',
  model: '模型调用',
  tool: '只读查询',
  validation: '结果校验',
};
export default function RunSteps({ run }: { run: AgentRun }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ['agent-steps', run.id],
    enabled: open,
    queryFn: () =>
      api
        .GET('/api/v1/web/agent-runs/{run_id}/steps', { params: { path: { run_id: run.id } } })
        .then(expectData),
    refetchInterval: ['queued', 'running'].includes(run.status) ? 2000 : false,
  });
  return (
    <details className="m2-run-steps" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        查看本轮运行记录 · {run.primary_role === 'support' ? '客服答疑' : '创作摄影师'}
      </summary>
      <p>
        记录公开执行步骤，不包含隐藏思考。Release：
        {String(run.release_json?.release_id ?? '历史版本')}
      </p>
      {query.error && <p role="alert">{query.error.message}</p>}
      <ol>
        {query.data?.map((step) => (
          <li key={step.id}>
            <strong>
              {kinds[step.kind] ?? step.kind} · {step.name}
            </strong>
            <span>
              {statuses[step.status] ?? step.status}
              {step.error_code ? ' · ' + step.error_code : ''}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

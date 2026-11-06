/** 只读查询证据卡：显示服务端观察时间和数值事实，不从模型文字解析状态。 */
import { Clock3 } from 'lucide-react';
import type { AgentObservation } from '@yingxu/api-client';
const errors: Record<string, string> = {
  TOOL_NOT_FOUND: '当前项目中没有可查询的任务。',
  TOOL_NOT_ALLOWED: '这项查询当前未开放。',
  TOOL_TIMEOUT: '查询超时，请稍后重新查询。',
  TOOL_REPEAT: '本轮已查询过相同内容，没有重复读取。',
  TOOL_INVALID_ARGUMENTS: '查询参数未通过校验。',
  TOOL_OUTPUT_LIMIT: '结果较多，请指定具体任务后查询。',
};
/** 插件结果也是不可信数据，只渲染已知字段，新增插件保留来源提示。 */
export default function ToolObservations({ observations }: { observations: AgentObservation[] }) {
  if (!observations.length) return null;
  return (
    <div className="at-tool-observations">
      {observations.map((item) => {
        const data = item.data ?? {};
        const jobs = Array.isArray(data.jobs)
          ? data.jobs.filter(
              (job): job is Record<string, unknown> => !!job && typeof job === 'object',
            )
          : [];
        const messages = Array.isArray(data.messages)
          ? data.messages.filter(
              (message): message is Record<string, unknown> =>
                !!message && typeof message === 'object',
            )
          : [];
        return (
          <div className="at-tool-fact" key={item.id}>
            <small>
              <Clock3 size={11} />
              {item.title} ·{' '}
              {new Date(item.observed_at).toLocaleTimeString('zh-CN', { hour12: false })}
            </small>
            {item.status === 'error' ? (
              <p>{errors[item.error_code ?? ''] ?? '这次查询未能完成，当前状态无法确认。'}</p>
            ) : item.name === 'get_entitlements' ? (
              <dl>
                {[
                  ['available', '可用'],
                  ['reserved', '预占'],
                  ['consumed', '已用'],
                ].map(([key, label]) => (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{typeof data[key] === 'number' ? String(data[key]) : '—'} 次</dd>
                  </div>
                ))}
              </dl>
            ) : item.name === 'get_job_status' ? (
              <>
                <p>
                  项目共 {typeof data.total === 'number' ? data.total : '—'} 项任务 ·
                  以下为本次查询快照
                </p>
                {jobs.length ? (
                  <ul>
                    {jobs.map((job, index) => (
                      <li key={typeof job.id === 'string' ? job.id : index}>
                        <strong>
                          第 {typeof job.item_index === 'number' ? job.item_index : '—'} 张 ·{' '}
                          {typeof job.status_label === 'string' ? job.status_label : '状态待确认'}
                        </strong>
                        {typeof job.reason === 'string' && <span>{job.reason}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>暂时没有生成任务。</p>
                )}
              </>
            ) : item.name === 'search_project_history' ? (
              <>
                <p>关键词：{typeof data.query === 'string' ? data.query : '—'} · 历史原话</p>
                {messages.length ? (
                  <ul>
                    {messages.map((message, index) => (
                      <li key={typeof message.message_id === 'string' ? message.message_id : index}>
                        <strong>
                          第 {typeof message.seq === 'number' ? message.seq : '—'} 条 ·{' '}
                          {message.role === 'user' ? '你' : 'Lumi'}
                          {typeof message.created_at === 'string' &&
                            ` · ${new Date(message.created_at).toLocaleString('zh-CN', { hour12: false })}`}
                        </strong>
                        <span>
                          {typeof message.text === 'string' ? message.text : ''}
                          {message.truncated === true ? '…（已截断，可在历史对话查看全文）' : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>可供回溯的记录中没有匹配原话。</p>
                )}
                <p>仅用于回溯，以当前确认要求为准；不代表当前次数或生成状态。</p>
              </>
            ) : (
              <p>只读查询已完成，结果已用于本轮回复。</p>
            )}
            <p className="at-tool-time">查询时刻的状态，后续可能变化。</p>
          </div>
        );
      })}
    </div>
  );
}

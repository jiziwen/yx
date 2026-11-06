/** 临时回复只按 Run/尝试/序号替换；不拼接 JSON，也不把片段晋升为提案或正式消息。 */
import type { AgentReplyPreview } from '@yingxu/api-client';

export type PreviewEntry = {
  attempt: number;
  seq: number;
  closed: boolean;
  preview: AgentReplyPreview | null;
};
export type PreviewMap = Record<string, PreviewEntry>;

export function applyReplyEvent(current: PreviewMap, raw: unknown, epoch: number): PreviewMap {
  if (!raw || typeof raw !== 'object') return current;
  const event = raw as Record<string, unknown>;
  const body = event.payload as Record<string, unknown> | undefined;
  const id = event.run_id;
  const attempt = event.attempt_no;
  if (
    typeof id !== 'string' ||
    id.length > 36 ||
    !id ||
    !Number.isInteger(attempt) ||
    typeof attempt !== 'number' ||
    attempt < 1 ||
    attempt > 4 ||
    !body ||
    body.privacy_epoch !== epoch
  )
    return current;
  const old = current[id];
  if (old?.closed || (old && attempt < old.attempt)) return current;
  const preview = body.preview;
  let entry: PreviewEntry;
  if (preview === null) {
    entry = {
      attempt,
      seq: old && attempt === old.attempt ? Number.MAX_SAFE_INTEGER : 0,
      closed: body.closed === true,
      preview: null,
    };
  } else {
    if (!preview || typeof preview !== 'object') return current;
    const value = preview as AgentReplyPreview;
    if (
      value.run_id !== id ||
      value.attempt_no !== attempt ||
      value.privacy_epoch !== epoch ||
      !Number.isInteger(value.seq) ||
      value.seq < 1 ||
      typeof value.text !== 'string' ||
      value.text.length > 2400 ||
      (old && attempt === old.attempt && value.seq <= old.seq)
    )
      return current;
    entry = { attempt, seq: value.seq, closed: false, preview: value };
  }
  // 当前项目只允许一个活跃 Run；有界保留近期尝试的墓碑来拒绝迟到事件。
  return Object.fromEntries(
    [...Object.entries(current).filter(([key]) => key !== id), [id, entry]].slice(-32),
  );
}

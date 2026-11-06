/** 翻页窗口与实时快照的合并边界，防止重复、丢失旧页或跨隐私代次。 */
import { describe, expect, it } from 'vitest';
import type { AgentConversation } from '../src/index';
import { mergeSnapshot } from '../../../apps/web/src/features/atelier/useConversationHistory';

function view(first: number, last: number, cursor: string | null, epoch = 0): AgentConversation {
  return {
    id: 'conversation',
    project_id: 'project',
    privacy_epoch: epoch,
    older_cursor: cursor,
    messages: Array.from({ length: last - first + 1 }, (_, i) => ({
      id: `message-${first + i}`,
      seq: first + i,
      text: `原话${first + i}`,
    })),
    runs: [],
    model: 'test',
    enabled: true,
  } as unknown as AgentConversation;
}

describe('conversation history window', () => {
  it('keeps loaded older pages while updating overlapping latest messages', () => {
    const merged = mergeSnapshot(view(1, 80, null), view(23, 82, 'cursor23'));
    expect(merged.messages).toHaveLength(82);
    expect(merged.messages[0].seq).toBe(1);
    expect(merged.older_cursor).toBeNull();
  });
  it('retains the oldest loaded cursor and replaces duplicate messages with authority', () => {
    const newest = view(22, 81, 'new');
    newest.messages[0].text = '最新已提交正文';
    const merged = mergeSnapshot(view(21, 80, 'old'), newest);
    expect(merged.messages).toHaveLength(61);
    expect(merged.messages.find((message) => message.seq === 22)?.text).toBe('最新已提交正文');
    expect(merged.older_cursor).toBe('old');
  });
  it('resets to a contiguous snapshot when a disconnected client misses a whole window', () => {
    const newest = view(100, 159, 'cursor100');
    expect(mergeSnapshot(view(1, 20, null), newest)).toBe(newest);
  });
  it('never carries an old project or privacy epoch into the new view', () => {
    const newest = view(90, 100, 'new', 1);
    expect(mergeSnapshot(view(1, 80, null), newest)).toBe(newest);
    expect(mergeSnapshot({ ...view(1, 80, null), project_id: 'other' }, newest)).toBe(newest);
  });
});

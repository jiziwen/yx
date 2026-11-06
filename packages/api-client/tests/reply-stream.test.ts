/** 临时回复顺序保护：重复/迟到/旧尝试和跨隐私代次不能污染气泡。 */
import { describe, expect, it } from 'vitest';
import {
  applyReplyEvent,
  type PreviewMap,
} from '../../../apps/web/src/features/atelier/replyStream';

function delta(attempt: number, seq: number, text: string, epoch = 0) {
  return {
    run_id: 'synthetic-run',
    attempt_no: attempt,
    payload: {
      privacy_epoch: epoch,
      preview: { run_id: 'synthetic-run', attempt_no: attempt, seq, text, privacy_epoch: epoch },
    },
  };
}
function reset(attempt: number, closed = false) {
  return {
    run_id: 'synthetic-run',
    attempt_no: attempt,
    payload: { privacy_epoch: 0, preview: null, closed },
  };
}

describe('reply stream ordering', () => {
  it('replaces complete prefixes and ignores duplicates/older sequence numbers', () => {
    const first = applyReplyEvent({}, delta(1, 2, '已经收到'), 0);
    expect(applyReplyEvent(first, delta(1, 1, '旧片段'), 0)).toBe(first);
    expect(applyReplyEvent(first, delta(1, 2, '重复片段'), 0)).toBe(first);
    const next = applyReplyEvent(first, delta(1, 4, '已经收到你的需求'), 0);
    expect(next['synthetic-run'].preview?.text).toBe('已经收到你的需求');
  });
  it('a new attempt replaces text and rejects an old attempt arriving later', () => {
    const first = applyReplyEvent({}, delta(1, 3, '旧尝试'), 0);
    const second = applyReplyEvent(first, delta(2, 1, '新尝试'), 0);
    expect(applyReplyEvent(second, delta(1, 99, '旧尝试的迟到文字'), 0)).toBe(second);
    expect(second['synthetic-run'].preview?.text).toBe('新尝试');
  });
  it('clearing the old attempt prevents resurrection but permits the next attempt', () => {
    let value = applyReplyEvent({}, delta(1, 2, '旧'), 0);
    value = applyReplyEvent(value, reset(1), 0);
    expect(applyReplyEvent(value, delta(1, 3, '旧恢复'), 0)).toBe(value);
    value = applyReplyEvent(value, reset(2), 0);
    value = applyReplyEvent(value, delta(2, 1, '新'), 0);
    expect(value['synthetic-run'].preview?.text).toBe('新');
  });
  it('a terminal run cannot resurrect a partial bubble', () => {
    const done = applyReplyEvent(applyReplyEvent({}, delta(1, 1, '正在'), 0), reset(1, true), 0);
    expect(done['synthetic-run'].preview).toBeNull();
    expect(applyReplyEvent(done, delta(2, 99, '迟到'), 0)).toBe(done);
  });
  it('ignores other epochs and malformed envelopes', () => {
    const value: PreviewMap = {};
    expect(applyReplyEvent(value, delta(1, 1, '其他授权', 1), 0)).toBe(value);
    for (const raw of [null, { payload: null }, delta(9, 1, '越界'), delta(1, -1, '坏序号')])
      expect(applyReplyEvent(value, raw, 0)).toBe(value);
  });
});

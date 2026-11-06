/** 对话通知、丢失校准和断线恢复；供应商仍为隔离环境的本地测试插件。 */
import { editIdea } from './studio-session';
import { test, expect, type Page, type BrowserContext } from '@playwright/test';
import type { AgentConversation } from '../../packages/api-client/src/index';

declare global {
  interface Window {
    __agentStreams: { closed: boolean; emit: (name: string) => void; fail: () => void }[];
  }
}

async function enter(page: Page, context: BrowserContext) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const response = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: '实时对话与提案对比验收', kind: 'portrait' },
  });
  const project = await response.json();
  await page.goto(`/projects/${project.id}/studio`);
  await expect(page.locator('.dp-chat')).toHaveAttribute('data-connection', 'live');
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  return project.id as string;
}

async function fakeStream(page: Page) {
  await page.addInitScript(() => {
    window.__agentStreams = [];
    class TestSource extends EventTarget {
      closed = false;
      onerror: (() => void) | null = null;
      constructor() {
        super();
        window.__agentStreams.push(this);
        queueMicrotask(() => this.emit('stream.ready'));
      }
      emit(name: string) {
        this.dispatchEvent(
          new MessageEvent(name, { data: JSON.stringify({ payload: { privacy_epoch: 0 } }) }),
        );
      }
      fail() {
        this.onerror?.();
      }
      close() {
        this.closed = true;
      }
    }
    window.EventSource = TestSource as unknown as typeof EventSource;
  });
}

test('真实 SSE 连接恢复已提交回复，提案显示原值与建议，应用仍不生成图片', async ({
  page,
  context,
}) => {
  const id = await enter(page, context);
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await editIdea(page, '保留原来的裙摆');
  await page.getByLabel('给 Lumi 留言').fill('换成薰衣草色的柔光');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  const diff = page.locator('.at-proposal-change').filter({ hasText: '创作要求' });
  await expect(diff.locator('.at-proposal-before')).toContainText('保留原来的裙摆');
  await expect(diff.locator('.at-proposal-after')).toContainText(
    '保留原来的裙摆；换成薰衣草色的柔光',
  );
  await expect(page.locator('.sx-idea-line')).toContainText('保留原来的裙摆');
  await page.getByRole('button', { name: '采用这个建议', exact: true }).click();
  await expect(page.locator('.sx-idea-line')).toContainText('保留原来的裙摆；换成薰衣草色的柔光');
  expect(await (await page.request.get(`/api/v1/web/projects/${id}/plans`)).json()).toEqual([]);
  expect(await (await page.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
  await page.reload();
  await expect(page.locator('.at-proposal-after')).toContainText('换成薰衣草色的柔光');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
});

test('连接健康但通知丢失时，活跃对话用权威快照校准且不重复消息', async ({ page, context }) => {
  await fakeStream(page);
  await page.clock.install();
  const id = await enter(page, context);
  let queued: AgentConversation | undefined;
  let freeze = false;
  await page.route(`**/projects/${id}/messages`, async (route) => {
    const response = await route.fetch();
    const run = await response.json();
    const snapshot = await (
      await context.request.get(`/api/v1/web/projects/${id}/conversation`)
    ).json();
    queued = {
      ...snapshot,
      runs: [run],
      messages: snapshot.messages.filter((item: { role: string }) => item.role === 'user'),
    };
    freeze = true;
    await route.fulfill({ response });
  });
  await page.route(`**/projects/${id}/conversation`, async (route) => {
    if (freeze) {
      freeze = false;
      await route.fulfill({ json: queued });
    } else await route.continue();
  });
  await page.getByLabel('给 Lumi 留言').fill('保留柔和自然光');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止', exact: true })).toBeVisible();
  await expect
    .poll(async () => {
      const value = await (
        await context.request.get(`/api/v1/web/projects/${id}/conversation`)
      ).json();
      return value.runs.at(-1)?.status;
    })
    .toBe('succeeded');
  await page.clock.fastForward(16000);
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toBeVisible();
  expect(await page.locator('.dp-message-you').count()).toBe(1);
  expect(await page.locator('.sx-suggestion').count()).toBe(1);
  const value = await (await context.request.get(`/api/v1/web/projects/${id}/conversation`)).json();
  expect(value.runs).toHaveLength(1);
  expect(value.runs[0].calls).toBe(1);
});

test('断线会重新订阅并同步快照，旧连接事件不影响新连接，撤销后清空对话', async ({
  page,
  context,
}) => {
  await fakeStream(page);
  await page.clock.install();
  const id = await enter(page, context);
  await page.getByLabel('给 Lumi 留言').fill('请记住：不要水印');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect
    .poll(async () => {
      const value = await (
        await context.request.get(`/api/v1/web/projects/${id}/conversation`)
      ).json();
      return value.runs.at(-1)?.status;
    })
    .toBe('succeeded');
  await page.evaluate(() => window.__agentStreams.at(-1)!.fail());
  await expect(page.locator('.dp-chat')).toHaveAttribute('data-connection', 'recovering');
  await page.clock.fastForward(1100);
  await expect(page.locator('.dp-chat')).toHaveAttribute('data-connection', 'live');
  await expect(page.getByRole('button', { name: '确认记住', exact: true })).toBeVisible();
  await page.evaluate(() => {
    const old = window.__agentStreams.find((stream) => stream.closed)!;
    old.emit('stream.revoked');
  });
  await expect(page.locator('.dp-chat')).toHaveAttribute('data-connection', 'live');
  await page.evaluate(() => window.__agentStreams.at(-1)!.emit('stream.revoked'));
  await expect(page.getByLabel('给 Lumi 留言')).toBeDisabled();
  await expect(page.locator('.dp-message-you')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认记住', exact: true })).toHaveCount(0);
});

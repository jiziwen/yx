/** 原生流式片段→数据库→SSE→气泡，明确本地样例，不调用真实供应商或用户照片。 */
import { test, expect, type Page, type BrowserContext } from '@playwright/test';

async function start(page: Page, context: BrowserContext) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const response = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: '流式对话验收', kind: 'portrait' },
  });
  const { id } = await response.json();
  await page.goto(`/projects/${id}/studio`);
  await expect(page.locator('.dp-chat')).toHaveAttribute('data-connection', 'live');
  await page.getByLabel('给 Lumi 留言').fill('测试流式回复：保持确认生成的边界');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.locator('.at-stream-reply')).toBeVisible({ timeout: 10000 });
  return id as string;
}

test('片段在最终消息之前逐步出现，提案只在完成后可应用且不产生图片', async ({ page, context }) => {
  const id = await start(page, context);
  const text = page.locator('.at-stream-reply .at-agent-text');
  const initial = (await text.innerText()).length;
  await expect(page.locator('.at-stream-reply')).toBeInViewport();
  await expect.poll(async () => (await text.innerText()).length).toBeGreaterThan(initial);
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toHaveCount(0);
  await expect(page.locator('.at-stream-reply')).toContainText('开发样例');
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator('.at-stream-reply')).toHaveCount(0);
  const view = await (await context.request.get(`/api/v1/web/projects/${id}/conversation`)).json();
  expect(view.messages.filter((item: { role: string }) => item.role === 'assistant')).toHaveLength(
    1,
  );
  expect(view.runs[0].reply_preview).toBeNull();
  expect(await (await context.request.get(`/api/v1/web/projects/${id}/plans`)).json()).toEqual([]);
  expect(await (await context.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
});

test('文字流中断线，后台完成后重连恢复最终消息，不重发调用或重复回复', async ({
  page,
  context,
}) => {
  const id = await start(page, context);
  await context.setOffline(true);
  await expect
    .poll(
      async () => {
        const view = await (
          await context.request.get(`/api/v1/web/projects/${id}/conversation`)
        ).json();
        return view.runs[0].status;
      },
      { timeout: 15000 },
    )
    .toBe('succeeded');
  await context.setOffline(false);
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.locator('.at-stream-reply')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('.sx-suggestion')).toHaveCount(1);
  expect(await page.locator('.dp-message-you').count()).toBe(1);
  const view = await (await context.request.get(`/api/v1/web/projects/${id}/conversation`)).json();
  expect(view.runs).toHaveLength(1);
  expect(view.runs[0].calls).toBe(1);
  expect(view.messages).toHaveLength(2);
});

test('流式回复中停止，清除片段且迟到结果不能提交提案', async ({ page, context }) => {
  const id = await start(page, context);
  await page.getByRole('button', { name: '停止', exact: true }).click();
  await expect(page.locator('.at-stream-reply')).toHaveCount(0);
  await expect(page.getByText('这次整理已停止，你可以继续补充想法。')).toBeVisible();
  await expect
    .poll(async () => {
      const view = await (
        await context.request.get(`/api/v1/web/projects/${id}/conversation`)
      ).json();
      return view.runs[0].status;
    })
    .toBe('cancelled');
  await expect(page.locator('.sx-suggestion')).toHaveCount(0);
  expect(await (await context.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
});

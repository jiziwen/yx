/** 第二批 Agent：显式确认记忆、刷新/清空、真实只读结果及生成确认边界。 */
import { test, expect } from '@playwright/test';

async function enter(
  page: import('@playwright/test').Page,
  context: import('@playwright/test').BrowserContext,
) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const response = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: '记忆与只读查询验收', kind: 'portrait' },
  });
  const project = await response.json();
  await page.goto(`/projects/${project.id}/studio`);
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  return project.id as string;
}

test('模型建议必须确认记住，刷新恢复并可明确清空，不产生图片任务', async ({ page, context }) => {
  const id = await enter(page, context);
  await page.getByLabel('给 Lumi 留言').fill('请记住：不要头纱');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.getByRole('button', { name: '确认记住', exact: true })).toBeEnabled();
  let memory = await (await page.request.get(`/api/v1/web/projects/${id}/memory`)).json();
  expect(memory.requirements).toEqual([]);
  await page.getByRole('button', { name: '确认记住', exact: true }).click();
  await expect(page.getByText('项目记忆 · 1 条')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  await expect(page.getByText('项目记忆 · 1 条')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '管理项目记忆' }).click();
  await expect(page.getByLabel('项目长期要求')).toHaveValue('不要头纱');
  await page.getByRole('button', { name: '清空内容', exact: true }).click();
  memory = await (await page.request.get(`/api/v1/web/projects/${id}/memory`)).json();
  expect(memory.requirements).toEqual(['不要头纱']);
  await page.getByRole('button', { name: '确认保存记忆', exact: true }).click();
  await expect(page.getByText('项目记忆 · 0 条')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  expect(await (await page.request.get(`/api/v1/web/projects/${id}/plans`)).json()).toEqual([]);
  expect(await (await page.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
});

test('只读工具显示实际次数和任务快照，多窗口记忆变更不能覆盖编辑', async ({ page, context }) => {
  const id = await enter(page, context);
  await page.request.post(`/api/v1/web/projects/${id}/trial-grants`);
  await page.getByLabel('给 Lumi 留言').fill('查询项目状态');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.locator('.at-tool-fact').filter({ hasText: '查询创作次数' })).toContainText(
    '8 次',
  );
  await expect(
    page.locator('.at-tool-fact').filter({ hasText: '查询生成进度与失败原因' }),
  ).toContainText('暂时没有生成任务');
  await expect(page.locator('.at-tool-fact').first()).toContainText('查询时刻的状态');
  await page.getByRole('button', { name: '管理项目记忆' }).click();
  await page.getByLabel('项目长期要求').fill('本窗口尚未确认的要求');
  await page.request.put(`/api/v1/web/projects/${id}/memory`, {
    data: { expected_revision: 0, expected_privacy_epoch: 0, requirements: ['另一窗口确认的要求'] },
  });
  await expect(page.getByText('项目记忆已在其他页面更新，请载入最新内容后再编辑。')).toBeVisible({
    timeout: 12000,
  });
  await expect(page.getByRole('button', { name: '确认保存记忆' })).toBeDisabled();
  await expect(page.getByLabel('项目长期要求')).toHaveValue('本窗口尚未确认的要求');
  await page.getByRole('button', { name: '载入最新记忆' }).click();
  await expect(page.getByLabel('项目长期要求')).toHaveValue('另一窗口确认的要求');
  await page.getByRole('button', { name: '确认保存记忆', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});

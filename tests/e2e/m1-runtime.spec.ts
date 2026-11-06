/** M1 后台调用证据读取真实 API，开发卡片只验证链路，费用保持未知。 */
import { test, expect } from '@playwright/test';
import { loginAdmin } from './admin-session';

test('M1 管理端展示调用证据与未知费用，已结算任务不可再次核对', async ({ page, context }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const phone = '137' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const created = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: 'M1 调用证据验收', kind: 'portrait' },
  });
  const project = await created.json();
  await context.request.post(`/api/v1/web/projects/${project.id}/trial-grants`);
  const saved = await context.request.post(`/api/v1/web/projects/${project.id}/plans`, {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: {
      mode: 'text',
      reference_asset_ids: [],
      style_id: 'portrait_portrait_01',
      style_version: '1',
      aspect_ratio: '3:4',
      count: 1,
      mood: '柔光',
      notes: '合成链路测试卡',
      expected_revision: project.brief_revision,
    },
  });
  expect(saved.status()).toBe(200);
  const accepted = await context.request.post(
    `/api/v1/web/approvals/${(await saved.json()).approval_id}/accept`,
    { headers: { 'Idempotency-Key': crypto.randomUUID() } },
  );
  const jobId = (await accepted.json()).job_ids[0];
  await expect
    .poll(
      async () => {
        const response = await context.request.get(`/api/v1/web/projects/${project.id}/jobs`);
        return (await response.json()).find((job: { id: string }) => job.id === jobId)?.status;
      },
      { timeout: 20000 },
    )
    .toBe('succeeded');
  expect(
    (await context.request.get(`http://127.0.0.1:5374/api/v1/admin/jobs/${jobId}`)).status(),
  ).toBe(401);
  await loginAdmin(context);
  await page.goto('http://127.0.0.1:5374/jobs');
  await page
    .getByRole('row')
    .filter({ hasText: jobId })
    .getByRole('button', { name: '查看详情' })
    .click();
  const detail = page.getByRole('region', { name: '调用详情' });
  await expect(detail.getByText('任务与调用证据')).toBeVisible();
  await expect(detail.getByText('任务已经结算。重复消息不会重复交付或扣除权益。')).toBeVisible();
  await expect(detail.getByRole('button', { name: '查询原任务' })).toBeDisabled();
  await expect(
    detail
      .locator('div')
      .filter({ has: page.locator('dt', { hasText: '确认费用' }) })
      .last(),
  ).toContainText('未知');
  const evidence = await context.request.get(`http://127.0.0.1:5374/api/v1/admin/jobs/${jobId}`);
  expect((await evidence.json()).attempt.actual_cost_micros).toBeNull();
  expect(errors).toEqual([]);
});

/** 管理端真实开发模型记录与独立21条分页夹具；不调用付费供应商。 */
import { test, expect } from '@playwright/test';
import { loginAdmin } from './admin-session';

const adminBase = 'http://127.0.0.1:5374';

test('工作室聊天产生可查询的模型调用，入参出参可见且没有图片副作用', async ({ page, context }) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (
    await context.request.post('/api/v1/web/auth/code', { data: { phone } })
  ).json();
  await context.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  const project = await (
    await context.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title: '模型调用记录验收', kind: 'portrait' },
    })
  ).json();
  await page.goto(`/projects/${project.id}/studio`);
  await page.getByLabel('给 Lumi 留言').fill('只整理需求：想要柔和光线和暖色调');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect
    .poll(
      async () => {
        const conversation = await (
          await context.request.get(`/api/v1/web/projects/${project.id}/conversation`)
        ).json();
        return conversation.runs[0]?.status;
      },
      { timeout: 15000 },
    )
    .toBe('succeeded');
  await loginAdmin(context);
  await page.goto(adminBase + '/model-calls');
  await expect(page.getByRole('link', { name: '模型调用', exact: true })).toBeVisible();
  const list = page.getByRole('region', { name: '模型调用列表' });
  await expect(list).toContainText('每页 20 条');
  await expect(list).toContainText('流式回复');
  await list.getByRole('button', { name: '查看入参 / 出参', exact: true }).first().click();
  const detail = page.getByRole('dialog', { name: '模型调用详情' });
  await expect(detail.getByLabel('调用入参')).toContainText('想要柔和光线和暖色调');
  await expect(detail.getByLabel('调用出参')).toContainText('开发样例');
  await expect(detail).toContainText(project.id);
  await expect(detail).toContainText('已返回');
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toEqual([]);
  await page.screenshot({ path: '.data/model-calls-detail-e2e.png', fullPage: true });
});

test('21条列表按20条翻页，弹框支持键盘关闭、焦点恢复和刷新', async ({ page, context }) => {
  await loginAdmin(context);
  const rows = Array.from({ length: 21 }, (_, index) => ({
    id: `synthetic-call-${index}`,
    created_at: '2026-10-23T08:00:00Z',
    provider_id: 'synthetic-provider',
    kind: 'llm',
    model: 'synthetic-model',
    operation: 'complete',
    status: 'succeeded',
    development_sample: true,
    project_id: null,
    owner_user_id: null,
    run_id: null,
    job_id: null,
    finished_at: '2026-10-23T08:00:01Z',
    latency_ms: 1000,
    http_status: 200,
    error_code: null,
    result_unknown: false,
    call_count: 1,
    lookup_count: 0,
    latest_at: '2026-10-23T08:00:01Z',
    latest_operation: 'complete',
  }));
  await page.route('**/api/v1/admin/model-calls?*', async (route) => {
    const current = Number(new URL(route.request().url()).searchParams.get('page') ?? 1);
    await route.fulfill({
      json: {
        items: rows.slice((current - 1) * 20, current * 20),
        page: current,
        page_size: 20,
        total: 21,
        total_pages: 2,
      },
    });
  });
  await page.route('**/api/v1/admin/model-calls/synthetic-call-*', (route) =>
    route.fulfill({
      json: {
        ...rows[0],
        request: { prompt: '合成测试' },
        response: { reply: '合成回复' },
        scrubbed: false,
        request_call_id: rows[0].id,
        response_call_id: rows[0].id,
        calls: [rows[0]],
        calls_page: 1,
        calls_total_pages: 1,
      },
    }),
  );
  await page.goto(adminBase + '/model-calls');
  const list = page.getByRole('region', { name: '模型调用列表' });
  await expect(list.locator('tbody tr')).toHaveCount(20);
  await expect(list).toContainText('第 1 / 2 页');
  await list.getByRole('button', { name: '查看入参 / 出参' }).first().click();
  await expect(page.getByRole('dialog', { name: '模型调用详情' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '模型调用详情' })).toHaveCount(0);
  await expect(list.getByRole('button', { name: '查看入参 / 出参' }).first()).toBeFocused();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(list.locator('tbody tr')).toHaveCount(1);
  await expect(list).toContainText('第 2 / 2 页');
  await expect(page.getByRole('dialog', { name: '模型调用详情' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(list.locator('tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: '上一页', exact: true }).click();
  await expect(list.locator('tbody tr')).toHaveCount(20);
});

test('图片任务弹框展示原始提示词和最近结果，逐次入出参可翻页查看', async ({ page, context }) => {
  await loginAdmin(context);
  const calls = Array.from({ length: 25 }, (_, index) => ({
    id: `image-call-${index}`,
    created_at: new Date(Date.UTC(2026, 9, 23, 8, 0, index)).toISOString(),
    provider_id: 'image-provider',
    kind: 'image',
    model: 'gpt-image-2',
    operation: index === 0 ? 'submit' : 'lookup',
    status: 'succeeded',
    development_sample: false,
    project_id: 'image-project',
    owner_user_id: 'image-owner',
    run_id: null,
    job_id: 'same-image-job',
    finished_at: null,
    latency_ms: 100,
    http_status: 200,
    error_code: null,
    result_unknown: false,
  }));
  const request = {
    method: 'POST',
    endpoint: 'https://api.302.ai/v1/images/edits',
    data: {
      model: 'gpt-image-2',
      prompt: '保留人物五官，柔和侧光，电影感暖色调',
      quality: 'low',
      size: '768x1024',
    },
  };
  const response = {
    status_code: 200,
    data: { data: [{ url: 'https://file.example.test/final.png' }] },
  };
  const summary = {
    ...calls[0],
    call_count: 25,
    lookup_count: 24,
    latest_at: calls[24].created_at,
    latest_operation: 'lookup',
    latency_ms: 2500,
  };
  await page.route('**/api/v1/admin/model-calls**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/model-calls')) {
      await route.fulfill({
        json: { items: [summary], page: 1, page_size: 20, total: 1, total_pages: 1 },
      });
    } else if (url.pathname.endsWith('/payload')) {
      const call = calls.find((call) => url.pathname.endsWith(`/${call.id}/payload`))!;
      await route.fulfill({
        json: {
          ...call,
          request:
            call.operation === 'submit'
              ? request
              : {
                  method: 'GET',
                  endpoint: 'https://api.302.ai/async_result',
                  params: { task_id: 'image-task' },
                },
          response: call.operation === 'submit' ? { task_id: 'image-task' } : response,
          scrubbed: false,
        },
      });
    } else {
      const callsPage = Number(url.searchParams.get('calls_page') ?? 1);
      await route.fulfill({
        json: {
          ...summary,
          request,
          response,
          scrubbed: false,
          request_call_id: calls[0].id,
          response_call_id: calls[24].id,
          calls: [...calls].reverse().slice((callsPage - 1) * 20, callsPage * 20),
          calls_page: callsPage,
          calls_total_pages: 2,
        },
      });
    }
  });
  await page.goto(adminBase + '/model-calls');
  const list = page.getByRole('region', { name: '模型调用列表' });
  await expect(list.locator('tbody tr')).toHaveCount(1);
  await expect(list).toContainText('合并 25 次请求 · 查询 24 次');
  const trigger = list.getByRole('button', { name: '查看入参 / 出参' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '模型调用详情' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('调用提示词')).toHaveText(request.data.prompt);
  await expect(dialog.getByLabel('调用入参')).toContainText('"quality": "low"');
  await expect(dialog.getByLabel('调用出参')).toContainText('final.png');
  await page.screenshot({ path: '.data/model-calls-image-dialog.png', fullPage: true });
  await dialog.getByText('每次请求明细（25 次）', { exact: true }).click();
  const history = dialog.locator('details');
  await expect(history.locator('tbody tr')).toHaveCount(20);
  await history.getByRole('button', { name: '查看本次入出参' }).first().click();
  await expect(dialog.getByLabel('调用入参')).toContainText('"method": "GET"');
  await expect(dialog.getByLabel('调用入参')).not.toContainText('prompt');
  await expect(dialog.getByLabel('调用提示词')).toHaveText(request.data.prompt);
  await dialog.getByRole('button', { name: '返回调用汇总' }).click();
  await expect(dialog.getByLabel('调用入参')).toContainText(request.data.prompt);
  await history.getByRole('button', { name: '下一页请求' }).click();
  await expect(history.locator('tbody tr')).toHaveCount(5);
  await history.getByRole('button', { name: '查看本次入出参' }).last().click();
  await expect(dialog.getByLabel('调用入参')).toContainText('"method": "POST"');
  await expect(dialog.getByLabel('调用出参')).toContainText('image-task');
  await dialog.getByRole('button', { name: '关闭详情' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.setViewportSize({ width: 420, height: 900 });
  await trigger.click();
  await expect(dialog.getByLabel('调用提示词')).toHaveText(request.data.prompt);
  const bounds = (await dialog.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(420);
  await page.screenshot({ path: '.data/model-calls-image-dialog-mobile.png', fullPage: true });
  await page.mouse.click(2, 2);
  await expect(dialog).toHaveCount(0);
});

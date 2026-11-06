/** 通过真实管理API补发与查询；丢失响应后刷新重试仍只发放一次，不调用模型。 */
import { test, expect, type APIRequestContext } from '@playwright/test';
import { loginAdmin } from './admin-session';
const adminUrl = 'http://127.0.0.1:5374';
async function createCustomer(request: APIRequestContext, title: string) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (await request.post('/api/v1/web/auth/code', { data: { phone } })).json();
  const user = await (
    await request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } })
  ).json();
  const project = await (
    await request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title, kind: 'portrait' },
    })
  ).json();
  return { user, project };
}

test('选择用户与所属项目增加次数，发放记录与用户端余额刷新后保持', async ({ page, context }) => {
  const { user, project } = await createCustomer(context.request, '后台补发合成验收');
  await loginAdmin(context);
  await page.goto(adminUrl + '/users');
  await page.getByRole('link', { name: '增加项目次数 / 查看发放记录' }).click();
  await expect(page.getByRole('heading', { name: '次数发放', exact: true })).toBeVisible();
  await page.getByLabel('搜索发放用户').fill(user.id);
  await expect(
    page.getByLabel('选择发放用户').getByRole('option', { name: new RegExp(user.id) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放用户').selectOption(user.id);
  await expect(
    page.getByLabel('选择发放项目').getByRole('option', { name: new RegExp(project.title) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放项目').selectOption(project.id);
  await page.getByLabel('增加次数').fill('8');
  await page.getByLabel('发放原因').fill('合成验收：补充创作次数');
  await page.getByRole('button', { name: '确认增加次数', exact: true }).dblclick();
  await expect(page.getByRole('status')).toContainText('发放 8 次');
  await expect(page.locator('.grant-balance')).toContainText('当前可用 8 次');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody tr')).toContainText('合成验收：补充创作次数');
  await expect(page.locator('tbody tr')).toContainText('人工补发');
  expect(
    (await (await context.request.get(`/api/v1/web/projects/${project.id}/entitlements`)).json())
      .available,
  ).toBe(8);
  await page.reload();
  await expect(page.locator('tbody')).toContainText(project.title);
  await page.goto(`/projects/${project.id}/studio`);
  await expect(page.locator('.sx-balance')).toContainText(/8\s*次可用/);
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(0);
});

test('发放成功但响应丢失，刷新恢复原请求且重试不重复发放', async ({ page, context }) => {
  const { user, project } = await createCustomer(context.request, '发放断线恢复验收');
  await loginAdmin(context);
  await page.goto(adminUrl + '/entitlements');
  await page.getByLabel('搜索发放用户').fill(user.id);
  await expect(
    page.getByLabel('选择发放用户').getByRole('option', { name: new RegExp(user.id) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放用户').selectOption(user.id);
  await expect(
    page.getByLabel('选择发放项目').getByRole('option', { name: new RegExp(project.title) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放项目').selectOption(project.id);
  await page.getByLabel('发放原因').fill('合成验收：丢失回包');
  await page.route('**/api/v1/admin/entitlements/grants', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const result = await route.fetch();
    expect(result.ok()).toBeTruthy();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: '确认增加次数', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('连接失败');
  await expect(page.getByLabel('选择发放用户')).toBeDisabled();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('button', { name: '重试本次发放' })).toBeEnabled();
  await expect(page.getByLabel('发放原因')).toHaveValue('合成验收：丢失回包');
  await page.unroute('**/api/v1/admin/entitlements/grants');
  await page.getByRole('button', { name: '重试本次发放' }).click();
  await expect(page.getByRole('status')).toContainText('发放 8 次');
  const records = await (
    await context.request.get(
      adminUrl + `/api/v1/admin/entitlements/grants?project_id=${project.id}`,
    )
  ).json();
  expect(records.total).toBe(1);
  expect(
    (await (await context.request.get(`/api/v1/web/projects/${project.id}/entitlements`)).json())
      .available,
  ).toBe(8);
  await page.screenshot({ path: '.data/entitlement-grants-recovery.png', fullPage: true });
});

test('切换用户清空项目，错误请求保留原因且不发放', async ({ page, context }) => {
  const first = await createCustomer(context.request, '第一位用户的项目');
  const second = await createCustomer(context.request, '第二位用户的项目');
  await loginAdmin(context);
  await page.goto(adminUrl + '/entitlements');
  await expect(
    page.getByLabel('选择发放用户').getByRole('option', { name: new RegExp(first.user.id) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放用户').selectOption(first.user.id);
  await expect(
    page.getByLabel('选择发放项目').getByRole('option', { name: new RegExp(first.project.title) }),
  ).toHaveCount(1);
  await page.getByLabel('选择发放项目').selectOption(first.project.id);
  await page.getByLabel('选择发放用户').selectOption(second.user.id);
  await expect(page.getByLabel('选择发放项目')).toHaveValue('');
  await expect(
    page.getByLabel('选择发放项目').getByRole('option', { name: new RegExp(first.project.title) }),
  ).toHaveCount(0);
  await expect(page.getByRole('button', { name: '确认增加次数' })).toBeDisabled();
  await page.getByLabel('选择发放项目').selectOption(second.project.id);
  await page.getByLabel('发放原因').fill('原因应保留');
  await page.route('**/api/v1/admin/entitlements/grants', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 409,
      json: { error: { code: 'PROJECT_ARCHIVED', message: '项目已归档' } },
    });
  });
  await page.getByRole('button', { name: '确认增加次数' }).click();
  await expect(page.getByRole('alert')).toContainText('项目已归档');
  await expect(page.getByLabel('发放原因')).toHaveValue('原因应保留');
  await expect(page.getByLabel('选择发放用户')).toBeEnabled();
  expect(
    (
      await (
        await context.request.get(`/api/v1/web/projects/${second.project.id}/entitlements`)
      ).json()
    ).available,
  ).toBe(0);
});

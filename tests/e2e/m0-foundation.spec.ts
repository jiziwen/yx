/** M0 跨前端验收：真实 API 连通、独立 Cookie 会话与管理权限隔离。 */
import { test, expect } from '@playwright/test';

test('M0 两个前端通过自己的代理读取 API，访客无管理权限', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const catalogResponse = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/web/catalog'),
  );
  await page.goto('/');
  expect((await catalogResponse).status()).toBe(200);
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeAttached();
  await expect(
    page.getByRole('button', { name: '开始我的创作', exact: true }).first(),
  ).toBeVisible();
  expect((await request.get('/api/v1/admin/me')).status()).toBe(401);
  await page.goto('http://127.0.0.1:5374/');
  await expect(page.getByRole('heading', { name: '映序管理工作台' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('M0 普通用户会话不能复用为管理身份，管理员使用独立 Cookie', async ({ page, context }) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('http://127.0.0.1:5373/api/v1/web/auth/code', {
    data: { phone },
  });
  const login = await context.request.post('http://127.0.0.1:5373/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  expect(login.status()).toBe(200);
  await page.goto('http://127.0.0.1:5374/');
  await expect(page.getByRole('button', { name: '登录工作台' })).toBeVisible();
  await page.getByLabel('管理密码').fill('yingxu-dev-admin');
  await page.getByRole('button', { name: '登录工作台' }).click();
  await expect(page.getByRole('heading', { name: '运营概览', exact: true })).toBeVisible();
  const admin = await context.request.get('http://127.0.0.1:5374/api/v1/admin/me');
  expect((await admin.json()).role).toBe('admin');
  const user = await context.request.get('http://127.0.0.1:5373/api/v1/web/me');
  expect((await user.json()).role).toBe('customer');
  const cookies = await context.cookies();
  expect(cookies.find((cookie) => cookie.name === 'yx_admin')).toMatchObject({
    httpOnly: true,
    path: '/api/v1/admin',
    sameSite: 'Lax',
  });
  expect(cookies.find((cookie) => cookie.name === 'yx_web')).toMatchObject({
    httpOnly: true,
    path: '/api/v1/web',
  });
});

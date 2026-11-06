/** 隔离验收复用同一已授权管理会话，避免把业务回归变成重复登录压力测试。 */
import { expect, type BrowserContext } from '@playwright/test';
let cookies: Awaited<ReturnType<BrowserContext['cookies']>> = [];
export async function loginAdmin(context: BrowserContext) {
  if (cookies.length) {
    await context.addCookies(cookies);
    const response = await context.request.get('http://127.0.0.1:5374/api/v1/admin/me');
    if (response.ok() && (await response.json()).role === 'admin') return;
  }
  const response = await context.request.post('http://127.0.0.1:5374/api/v1/admin/auth/login', {
    data: { username: 'admin', password: process.env.ADMIN_PASSWORD ?? 'yingxu-dev-admin' },
  });
  expect(response.ok()).toBeTruthy();
  cookies = (await context.cookies()).filter((cookie) => cookie.name === 'yx_admin');
}

/** M2正式知识库与客服闭环；隔离开发embedding/模型，不发送真实短信或创建图片。 */
import { test, expect, type BrowserContext, type Page } from '@playwright/test';
const backend = '/api/v1';
import { loginAdmin } from './admin-session';
async function login(context: BrowserContext) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post(`${backend}/web/auth/code`, { data: { phone } });
  expect(
    (
      await context.request.post(`${backend}/web/auth/login`, {
        data: { phone, code: (await code.json()).debug_code },
      })
    ).ok(),
  ).toBe(true);
}

async function enterSupport(page: Page, context: BrowserContext) {
  await login(context);
  await page.goto('/support');
  await expect(page.getByLabel('把问题告诉 Lumi')).toBeEnabled();
}

test('知识导入预览发布→指南→客服RAG引用→下架后旧引用失效', async ({ page, context }) => {
  await loginAdmin(context);
  await login(context);
  await page.goto('http://127.0.0.1:5374/knowledge');
  await page.getByRole('button', { name: '新建知识文档', exact: true }).click();
  await page.getByLabel('知识标题', { exact: true }).fill('蓝月参考照准备指南');
  await page.getByLabel('内容摘要', { exact: true }).fill('准备清晰自然的参考照');
  await page
    .getByLabel('知识正文', { exact: true })
    .fill(
      '蓝月参考照准备：使用清晰自然光的正面照片，脸部不被遮挡。不要使用严重滤镜。本指南是隔离开发样例。',
    );
  await page.getByRole('button', { name: '导入并建立索引', exact: true }).click();
  await expect(page.getByText('可预览发布', { exact: false })).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: '预览正文', exact: true }).click();
  const publish = page.getByRole('button', { name: '审核并发布', exact: true });
  await expect(publish).toBeEnabled();
  await publish.click();
  await expect(page.getByText('当前发布', { exact: false })).toBeVisible();
  await page.goto('http://127.0.0.1:5373/guides');
  await page.getByRole('button', { name: /蓝月参考照准备指南/ }).click();
  await expect(page.getByRole('dialog')).toContainText('不要使用严重滤镜');
  await page.getByRole('button', { name: '关闭弹窗', exact: true }).click();
  await page.goto('/support');
  await page.getByLabel('把问题告诉 Lumi').fill('查询知识：蓝月参考照准备');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  const source = page.getByRole('button', { name: '[1] 蓝月参考照准备指南 · v1', exact: true });
  await expect(source).toBeVisible({ timeout: 15000 });
  await source.click();
  await expect(page.getByRole('dialog')).toContainText('清晰自然光');
  await page.getByRole('button', { name: '关闭弹窗', exact: true }).click();
  const staff = await context.newPage();
  await staff.goto('http://127.0.0.1:5374/knowledge');
  await staff.getByRole('button', { name: /文档 1/ }).click();
  await staff.getByRole('button', { name: '下架此版本', exact: true }).click();
  await expect(staff.getByRole('button', { name: '下架此版本', exact: true })).toHaveCount(0);
  await source.click();
  await expect(page.getByRole('alert')).toContainText('已下架');
  await staff.close();
});

test('用户请求人工→员工领取回复→交还机器人，人工期间不创建新Run', async ({ page, context }) => {
  await enterSupport(page, context);
  await loginAdmin(context);
  await page.getByRole('button', { name: '留言请求人工', exact: true }).click();
  await expect(page.getByRole('heading', { name: '已留言，等待人工领取' })).toBeVisible();
  const staff = await context.newPage();
  await staff.goto('http://127.0.0.1:5374/support');
  await staff
    .getByRole('button', { name: /待领取/ })
    .last()
    .click();
  await staff.getByRole('button', { name: '领取此会话', exact: true }).click();
  await expect(page.getByRole('heading', { name: '人工客服正在陪你处理' })).toBeVisible();
  await page.getByLabel('把问题告诉 Lumi').fill('我需要人工帮忙核对问题。');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await staff.getByLabel('人工回复', { exact: true }).fill('你好，人工客服已收到，我们一起核对。');
  await staff.getByRole('button', { name: '发送人工回复', exact: true }).click();
  await expect(page.getByText('你好，人工客服已收到，我们一起核对。', { exact: true })).toBeVisible(
    { timeout: 10000 },
  );
  await staff.getByRole('button', { name: '交还机器人', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Lumi · 陪伴与帮助', exact: true })).toBeVisible({
    timeout: 10000,
  });
  await expect(page.locator('.m2-run-steps')).toHaveCount(0);
  await page.getByLabel('把问题告诉 Lumi').fill('请解释使用规则');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(
    page.getByText('开发样例：这里可以查询规则或请求人工客服。创作提案请返回工作室整理。', {
      exact: true,
    }),
  ).toBeVisible({ timeout: 10000 });
  await page.getByText('查看本轮运行记录 · 客服答疑', { exact: true }).click();
  await expect(page.locator('.m2-run-steps')).toContainText('模型调用');
  await staff.close();
});

test('无项目客服手机布局可用，更多历史分页不创建模型调用', async ({ page, context }) => {
  await login(context);
  const opened = await context.request.post('/api/v1/web/conversations', { data: {} });
  const chat = await opened.json();
  await context.request.post(`/api/v1/web/conversations/${chat.id}/handoff`, {
    data: { expected_revision: 0 },
  });
  await loginAdmin(context);
  await context.request.post(`http://127.0.0.1:5374/api/v1/admin/support/${chat.id}/claim`, {
    data: { expected_revision: 1 },
  });
  for (let index = 0; index < 45; index++) {
    const response = await context.request.post(`/api/v1/web/conversations/${chat.id}/messages`, {
      data: {
        client_message_id: crypto.randomUUID(),
        text: `历史人工消息 ${index + 1}`,
        expected_revision: 2,
        expected_privacy_epoch: 0,
      },
    });
    expect(response.status()).toBe(202);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/support');
  await expect(page.locator('.m2-chat-message')).toHaveCount(40);
  await page.getByRole('button', { name: '查看更早的客服消息', exact: true }).click();
  await expect(page.locator('.m2-chat-message')).toHaveCount(45);
  await expect(page.getByText('历史人工消息 1', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  const state = await (await context.request.get(`/api/v1/web/conversations/${chat.id}`)).json();
  expect(state.runs).toEqual([]);
});

/** 动态素材真实上传/发布与已打开工作室自动同步；全为合成图片，不请求付费模型。 */
import { test, expect, type Page } from '@playwright/test';
import { loginAdmin } from './admin-session';
const adminBase = 'http://127.0.0.1:5374';
const synthetic = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAABMklEQVR4nO3TMREAIBDEwAf/dnCAB+wgY5usgSsyt949E2fD7RTA6wFYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACjDWB0PEA1B5pEqSAAAAAElFTkSuQmCC',
  'base64',
);

async function newTheme(page: Page, name: string, id: string) {
  await page.getByRole('button', { name: '新增套系', exact: true }).click();
  await page.getByLabel('套系名称', { exact: true }).fill(name);
  await page.getByLabel('套系标识', { exact: true }).fill(id);
  await page.getByRole('button', { name: '添加镜头', exact: true }).click();
  await page.getByLabel('镜头 1 名称', { exact: true }).fill('合成紫色光影');
  await page
    .getByLabel('镜头 1 图片', { exact: true })
    .setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: synthetic });
  await page.getByRole('button', { name: '上传镜头 1 图片', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '图片已上传' })).toBeVisible();
  await page
    .getByLabel('镜头 1 来源', { exact: true })
    .fill('合成色块：本次验收自制图片，用途记录为测试夹具');
  for (const use of ['网站展示', '衍生创作', '发送给模型处理'])
    await page.getByLabel(`镜头 1 ${use}`, { exact: true }).check();
}

test('上传来源用途保存即生效，已打开工作室自动获取新套系，无生成副作用', async ({
  page,
  context,
}) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (
    await context.request.post('/api/v1/web/auth/code', { data: { phone } })
  ).json();
  await context.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  const project = await (
    await context.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title: '目录热更新验收', kind: 'portrait' },
    })
  ).json();
  const studio = await context.newPage();
  await studio.goto(`/projects/${project.id}/studio`);
  await studio.getByRole('button', { name: '风格参考图（选填）', exact: true }).click();
  await expect(studio.getByLabel('创作风格')).toBeEnabled();
  await loginAdmin(context);
  await page.goto(adminBase + '/theme-materials');
  const id = 'e2e_live_' + Date.now();
  await newTheme(page, '动态合成主题', id);
  const before = await (await context.request.get('/api/v1/web/catalog')).json();
  expect(before.styles.some((s: { id: string }) => s.id === id)).toBeFalsy();
  await page.getByRole('button', { name: '保存并生效', exact: true }).dblclick();
  await expect(page.getByRole('status').filter({ hasText: '已保存并生效' })).toBeVisible();
  await expect(page.locator('tbody')).toContainText(id);
  await page.getByRole('button', { name: '查看本版', exact: true }).first().click();
  await expect(page.getByRole('region', { name: '历史版本内容' })).toContainText('合成色块');
  await expect(page.getByRole('region', { name: '历史版本内容' })).toContainText('模型处理：允许');
  await page.getByRole('button', { name: '收起历史内容', exact: true }).click();
  const current = await (await context.request.get('/api/v1/web/catalog')).json();
  const style = current.styles.find((s: { id: string }) => s.id === id);
  expect(style.shots[0].rights_approved).toBeTruthy();
  expect((await context.request.get(style.shots[0].image)).ok()).toBeTruthy();
  await studio.bringToFront();
  await expect(
    studio.getByLabel('创作风格').getByRole('option', { name: '动态合成主题', exact: true }),
  ).toHaveCount(1, { timeout: 12000 });
  await studio.getByLabel('创作风格').selectOption(id);
  await expect(studio.getByRole('button', { name: '使用风格参考 1', exact: true })).toContainText(
    '合成紫色光影',
  );
  await expect(
    studio.getByRole('button', { name: '使用风格参考 1', exact: true }),
  ).not.toContainText('内测');
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(0);
  await page.bringToFront();
  await page.reload();
  await page.getByLabel('编辑主题套系').selectOption(id);
  await expect(page.getByLabel('镜头 1 来源')).toHaveValue(/合成色块/);
  await expect(page.getByLabel('镜头 1 发送给模型处理', { exact: true })).toBeChecked();
  await page.screenshot({ path: '.data/theme-materials-published.png', fullPage: true });
  // 原图仍存储，取消展示后已打开目录和公开内容一起撤回。
  await page.getByLabel('镜头 1 网站展示', { exact: true }).uncheck();
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '已保存并生效' })).toBeVisible();
  expect((await context.request.get(style.shots[0].image)).ok()).toBeFalsy();
  await studio.bringToFront();
  await expect(studio.getByRole('button', { name: '使用风格参考 1', exact: true })).toHaveCount(0, {
    timeout: 12000,
  });
  await studio.close();
});

test('保存回包丢失后刷新重试不重复发布，替换图片清除旧来源用途', async ({ page, context }) => {
  await loginAdmin(context);
  await page.goto(adminBase + '/theme-materials');
  const id = 'e2e_recover_' + Date.now();
  await newTheme(page, '保存恢复合成主题', id);
  const initial = await (
    await context.request.get(adminBase + '/api/v1/admin/theme-materials')
  ).json();
  await page.route('**/api/v1/admin/theme-materials', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    expect((await route.fetch()).ok()).toBeTruthy();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('连接失败');
  await page.reload();
  await expect(page.getByRole('button', { name: '重试本次保存', exact: true })).toBeEnabled();
  await expect(page.getByLabel('套系名称', { exact: true })).toHaveValue('保存恢复合成主题');
  await page.unroute('**/api/v1/admin/theme-materials');
  await page.getByRole('button', { name: '重试本次保存', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '已保存并生效' })).toBeVisible();
  expect(
    (await (await context.request.get(adminBase + '/api/v1/admin/theme-materials')).json())
      .revision,
  ).toBe(initial.revision + 1);
  await page
    .getByLabel('镜头 1 图片', { exact: true })
    .setInputFiles({ name: 'replacement.png', mimeType: 'image/png', buffer: synthetic });
  await page.getByRole('button', { name: '上传镜头 1 图片', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '图片已上传' })).toBeVisible();
  await expect(page.getByLabel('镜头 1 来源', { exact: true })).toHaveValue('');
  for (const use of ['网站展示', '衍生创作', '发送给模型处理'])
    await expect(page.getByLabel(`镜头 1 ${use}`, { exact: true })).not.toBeChecked();
});

test('陈旧页面保存不能覆盖新版本，来源和编辑内容保留供核对', async ({ page, context }) => {
  await loginAdmin(context);
  await page.goto(adminBase + '/theme-materials');
  const id = 'e2e_stale_' + Date.now();
  await newTheme(page, '并发编辑合成主题', id);
  const data = await (
    await context.request.get(adminBase + '/api/v1/admin/theme-materials')
  ).json();
  const existing = data.styles[0];
  const { version: _version, ...style } = existing;
  style.shots = existing.shots.map((shot: Record<string, unknown>) =>
    Object.fromEntries(
      Object.entries(shot).filter(
        ([key]) =>
          !['image', 'checksum', 'development_only', 'rights_approved', 'reviewed_by'].includes(
            key,
          ),
      ),
    ),
  );
  expect(
    (
      await context.request.post(adminBase + '/api/v1/admin/theme-materials', {
        data: { request_key: crypto.randomUUID(), expected_revision: data.revision, style },
      })
    ).ok(),
  ).toBeTruthy();
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('其他管理员已更新主题目录');
  await expect(page.getByLabel('套系名称', { exact: true })).toHaveValue('并发编辑合成主题');
  await expect(page.getByLabel('镜头 1 来源', { exact: true })).toHaveValue(/合成色块/);
  const current = await (await context.request.get('/api/v1/web/catalog')).json();
  expect(current.styles.some((s: { id: string }) => s.id === id)).toBeFalsy();
});

test('保存内测配置明确提示零张可创作，补齐来源与用途后只开放对应镜头', async ({
  page,
  context,
}) => {
  await loginAdmin(context);
  await page.goto(adminBase + '/theme-materials');
  await page.getByLabel('编辑主题套系').selectOption('portrait_portrait_01');
  const readiness = page.getByRole('note', { name: '创作开放检查', exact: true });
  await expect(readiness).toContainText(/0\s*\/\s*2 张可用于创作/);
  const missing = page.getByRole('note', { name: '镜头 1 开放缺项', exact: true });
  await expect(missing).toContainText('来源与使用依据、网站展示、衍生创作、发送给模型处理');
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '已保存并生效' })).toContainText(
    '0 张可用于创作，2 张未开放创作',
  );
  await expect(missing).toBeVisible();
  await page
    .getByLabel('镜头 1 来源', { exact: true })
    .fill('隔离合成验收：仅用于测试用途配置，不代真实素材批准');
  for (const use of ['网站展示', '衍生创作', '发送给模型处理'])
    await page.getByLabel(`镜头 1 ${use}`, { exact: true }).check();
  await expect(readiness).toContainText(/1\s*\/\s*2 张可用于创作/);
  await expect(missing).toHaveCount(0);
  await page.getByRole('button', { name: '保存并生效', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '已保存并生效' })).toContainText(
    '1 张可用于创作，1 张未开放创作',
  );
  const catalog = await (await context.request.get('/api/v1/web/catalog')).json();
  const style = catalog.styles.find((item: { id: string }) => item.id === 'portrait_portrait_01');
  expect(
    style.shots.find((item: { id: string }) => item.id === 'scene').rights_approved,
  ).toBeTruthy();
  expect(
    style.shots.find((item: { id: string }) => item.id === 'portrait').development_only,
  ).toBeTruthy();
});

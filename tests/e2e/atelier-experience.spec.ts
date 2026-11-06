/** 正式体验的入口、草稿和权限边界；测试只创建隔离的本地测试账户与项目。 */
import { editIdea, closeMaterial } from './studio-session';
import { test, expect } from '@playwright/test';

test('首页想法带入草稿，Agent 对话持久化且不自动保存或执行', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  if (await page.getByRole('button', { name: '跳过开场 · Esc' }).isVisible())
    await page.getByRole('button', { name: '跳过开场 · Esc' }).click();
  const brief = '想拍一组个人写真，留住夏天的自然光。';
  await page.getByLabel('告诉 Lumi 你的拍摄想法').fill(brief);
  await page.getByRole('button', { name: '和 Lumi 开始创作', exact: true }).click();
  await page
    .getByLabel('手机号', { exact: true })
    .fill('139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0'));
  await page.getByRole('button', { name: '获取验证码', exact: true }).click();
  await expect(page.getByLabel('验证码', { exact: true })).toHaveValue(/\d{6}/);
  await page.getByRole('button', { name: '进入我的工作室' }).click();
  await expect(page.getByRole('dialog')).toContainText('为故事，写一个名字。');
  await page.getByLabel('项目名称').fill('首页想法带入验收');
  await expect(page.getByLabel('创作类型')).toHaveValue('portrait');
  await page.getByRole('button', { name: '开启这段故事' }).click();
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await expect(page.locator('.sx-idea-line')).toContainText(brief);
  expect(page.url()).not.toContain(encodeURIComponent(brief));
  expect(JSON.stringify(await page.evaluate(() => history.state))).not.toContain(brief);
  await page.getByLabel('给 Lumi 留言').fill('我想让裙摆被风吹起来');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toBeVisible();
  await expect(page.locator('.sx-idea-line')).toContainText(brief);
  await page.getByRole('button', { name: '采用这个建议', exact: true }).click();
  await expect(page.locator('.sx-idea-line')).toContainText(brief + '；我想让裙摆被风吹起来');
  const projectId = page.url().split('/projects/')[1].split('/')[0];
  expect(await (await page.request.get(`/api/v1/web/projects/${projectId}/plans`)).json()).toEqual(
    [],
  );
  expect(await (await page.request.get(`/api/v1/web/projects/${projectId}/jobs`)).json()).toEqual(
    [],
  );
  expect(errors).toEqual([]);
  await page.reload();
  await expect(page.getByRole('log', { name: '摄影师创作引导' })).toContainText(
    '我想让裙摆被风吹起来',
  );
  await expect(page.locator('.dp-chat')).not.toContainText('local-llm');
  await expect(page.locator('.dp-chat').getByRole('heading', { name: 'Lumi AI' })).toBeVisible();
});

test('窄屏可访问真实人物入口与提案，切换主题不丢草稿', async ({ page, context }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const project = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: '窄屏创作验收', kind: 'portrait' },
  });
  const { id } = await project.json();
  await page.goto(`/projects/${id}/studio`);
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await expect(page.locator('.sx-modes')).toBeVisible();
  await editIdea(page, '窄屏也要保留的草稿');
  await page.getByRole('button', { name: '更换主题外观', exact: true }).click();
  await page.getByRole('button', { name: '切换主题：晴日来信', exact: true }).click();
  await expect(page.locator('.sx-idea-line')).toContainText('窄屏也要保留的草稿');
  await page.locator('.cx-canvas').getByRole('button', { name: '人物参考', exact: true }).click();
  await expect(page.getByRole('button', { name: '添加第一位主角', exact: true })).toBeVisible();
  await closeMaterial(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
});

test('Agent 建议不能覆盖用户后来修改的草稿', async ({ page, context }) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const response = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: 'Agent 草稿冲突验收', kind: 'portrait' },
  });
  const project = await response.json();
  await page.goto(`/projects/${project.id}/studio`);
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await page.getByLabel('给 Lumi 留言').fill('把光线调柔和一点');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  const apply = page.getByRole('button', { name: '采用这个建议', exact: true });
  await expect(apply).toBeEnabled();
  await editIdea(page, '我手动添加的新要求，必须保留');
  await expect(apply).toBeDisabled();
  await expect(page.locator('.cx-canvas')).toContainText('草稿已有新修改');
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/plans`)).json()).toEqual(
    [],
  );
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json()).toEqual(
    [],
  );
});

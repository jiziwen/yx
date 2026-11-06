/** 从真实页面与 API 验证确认、权益和交付；只使用程序合成的无人物图片。 */
import { material, closeMaterial, editIdea } from './studio-session';
import { test, expect, type Page } from '@playwright/test';

/** 每次用新测试账号登录；开发验证码来源于本地服务，无真实短信。 */
async function login(page: Page) {
  await page.goto('/');
  if (await page.getByRole('button', { name: '跳过开场 · Esc' }).isVisible())
    await page.getByRole('button', { name: '跳过开场 · Esc' }).click();
  await page.getByRole('button', { name: '登录我的工作室', exact: true }).click();
  await page
    .getByLabel('手机号', { exact: true })
    .fill('139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0'));
  await page.getByRole('button', { name: '获取验证码', exact: true }).click();
  await expect(page.getByLabel('验证码', { exact: true })).toHaveValue(/\d{6}/);
  await page.getByRole('button', { name: '进入我的工作室' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
}

/** 直接使用 PNG 字节作为 synthetic fixture，仓库不包含真人资料。 */
function referenceImage() {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAABMklEQVR4nO3TMREAIBDEwAf/dnCAB+wgY5usgSsyt949E2fD7RTA6wFYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACjDWB0PEA1B5pEqSAAAAAElFTkSuQmCC',
    'base64',
  );
}

test('固定创作从上传到交付，确认前没有 Job', async ({ page }) => {
  await login(page);
  await page.getByRole('link', { name: '我的项目', exact: true }).first().click();
  await page.getByRole('button', { name: '新建项目', exact: true }).click();
  await page.getByLabel('项目名称').fill('E2E 合成参考图');
  await page.getByLabel('创作类型').selectOption('portrait');
  await page.getByRole('button', { name: '开启这段故事' }).click();
  await page.locator('.cx-canvas').getByRole('button', { name: '人物参考', exact: true }).click();
  await page.getByRole('button', { name: '添加第一位主角' }).click();
  await page.getByPlaceholder('例如：我').fill('合成人物');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: '确认并添加' }).click();
  await page
    .getByLabel('上传合成人物参考照')
    .setInputFiles({ name: 'synthetic.png', mimeType: 'image/png', buffer: referenceImage() });
  await expect(
    page.getByRole('button', { name: '选择参考照片：合成人物 1', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await closeMaterial(page);
  await page
    .locator('.sx-studio-status')
    .getByRole('button', { name: /领取 8 次内测试用/ })
    .click();
  await page.locator('.cx-canvas').getByLabel('成片张数').selectOption('2');
  await editIdea(page, '主题切换必须保留的草稿');
  await material(page, '风格参考图（选填）');
  const styleBefore = await page.getByLabel('创作风格').inputValue();
  await closeMaterial(page);
  await page.getByRole('button', { name: '更换主题外观', exact: true }).click();
  await page.getByRole('button', { name: '切换主题：海岛叙事', exact: true }).click();
  await expect(page.locator('.sx-idea-line')).toContainText('主题切换必须保留的草稿');
  await material(page, '风格参考图（选填）');
  await expect(page.getByLabel('创作风格')).toHaveValue(styleBefore);
  await closeMaterial(page);
  const canvas = page.locator('.cx-canvas');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  await editIdea(page, '更新后的要求自动准备');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  const id = page.url().split('/projects/')[1].split('/')[0];
  expect(await (await page.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
  await canvas.getByRole('button', { name: /^确认生成/ }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(canvas.getByAltText('开发测试卡片', { exact: true })).toHaveCount(2, {
    timeout: 20000,
  });
  await canvas.getByRole('link', { name: '查看与下载全部作品' }).click();
  await expect(page.getByRole('heading', { name: '把喜欢，留在这里。' })).toBeVisible();
  await expect(page.getByRole('link', { name: '下载作品1' })).toBeVisible();
});

test('六套主题切换后仍能浏览首页', async ({ page }) => {
  await page.goto('/');
  if (await page.getByRole('button', { name: '跳过开场 · Esc' }).isVisible())
    await page.getByRole('button', { name: '跳过开场 · Esc' }).click();
  for (const name of ['绯红剧场', '雾光艺廊', '晴日来信', '海岛叙事', '东方喜事', '玫瑰画廊']) {
    await page.getByRole('button', { name: '切换主题：' + name, exact: true }).click();
    await expect(page.locator('.studio-theme')).toHaveAttribute(
      'data-style',
      {
        绯红剧场: 'film',
        雾光艺廊: 'portrait',
        晴日来信: 'fresh',
        海岛叙事: 'coast',
        东方喜事: 'oriental',
        玫瑰画廊: 'rose',
      }[name]!,
    );
    await expect(
      page.getByRole('button', { name: '开始我的创作', exact: true }).first(),
    ).toBeVisible();
  }
});

test('管理端保持独立登录入口', async ({ page }) => {
  await page.goto('http://127.0.0.1:5374/');
  await expect(page.getByRole('heading', { name: '映序管理工作台' })).toBeVisible();
  await page.getByLabel('管理密码').fill('yingxu-dev-admin');
  await page.getByRole('button', { name: '登录工作台' }).click();
  await page.getByRole('link', { name: '模块与配置' }).click();
  await expect(page.getByRole('heading', { name: '业务模块', exact: true })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'local-image', exact: true })).toBeVisible();
});

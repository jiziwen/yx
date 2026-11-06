/** 后台模型设置通过真实 API 发布；测试保持网关关闭，不产生真实付费调用。 */
import { test, expect } from '@playwright/test';
import { loginAdmin } from './admin-session';

test('保存后刷新恢复全部配置，审核启用同步表单，并且没有密钥输入或读取字段', async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await loginAdmin(context);
  await page.goto('http://127.0.0.1:5374/models');
  await expect(page.getByRole('heading', { name: '302.AI 模型配置' })).toBeVisible();
  await expect(
    page.getByText('尺寸不限，按用户选择或底图实际尺寸发送，由模型接口处理。', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('group', { name: '允许画幅' })).toHaveCount(0);
  await expect(page.getByLabel('文生图模型', { exact: true })).toHaveValue('gpt-image-2');
  await expect(page.getByLabel('图片质量档位')).toHaveValue('low');
  await expect(page.getByLabel('大语言模型 ID')).toHaveValue('claude-sonnet-5-5');
  await expect(page.getByLabel('开启真实图片模型')).not.toBeChecked();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.getByLabel('文生图模型', { exact: true }).fill('gpt-image-future-test');
  await page.getByLabel('大语言模型 ID').fill('test-chat-model');
  await page.getByLabel('视觉模型 ID').fill('test-vision-model');
  await page.getByLabel('单次图片上限', { exact: true }).fill('3');
  await page.getByLabel('最长边像素').fill('1536');
  await page.getByLabel('请求图片总字节上限').fill('5000000');
  await page.getByLabel('输出 token 上限', { exact: true }).fill('640');
  await page.getByRole('button', { name: '保存为候选新版本' }).click();
  await expect(page.getByRole('status')).toContainText('候选已保存');
  await expect(page.getByRole('button', { name: '已保存候选', exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByText('已载入保存的候选配置', { exact: true })).toBeVisible();
  await expect(page.getByLabel('文生图模型', { exact: true })).toHaveValue('gpt-image-future-test');
  await expect(page.getByLabel('大语言模型 ID')).toHaveValue('test-chat-model');
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue('test-vision-model');
  await expect(page.getByLabel('单次图片上限', { exact: true })).toHaveValue('3');
  await expect(page.getByLabel('最长边像素')).toHaveValue('1536');
  await expect(page.getByLabel('请求图片总字节上限')).toHaveValue('5000000');
  await expect(page.getByLabel('输出 token 上限', { exact: true })).toHaveValue('640');
  const first = await (
    await context.request.get('http://127.0.0.1:5374/api/v1/admin/model-settings/ai302')
  ).json();
  expect(first.image.text_model).toBe('gpt-image-2');
  expect(first.revision).toBe(0);
  // 先回到生效值，再审核候选，验证发布回调确实替换表单而非沿用原草稿。
  await page.getByRole('button', { name: '使用当前生效配置' }).click();
  await expect(page.getByLabel('文生图模型', { exact: true })).toHaveValue('gpt-image-2');
  await page.getByRole('button', { name: '查看 / 审核启用', exact: true }).first().click();
  await page.getByLabel('disabled-routes 实测记录位置与结论').fill('synthetic disabled routes');
  await page.getByLabel('本次已核对实际费用（人民币）').fill('0');
  await page.getByLabel('账单记录位置').fill('synthetic zero network');
  await page.getByLabel('人工验收结论').fill('仅测试关闭真实供应商的版本切换');
  await page.getByRole('checkbox', { name: /我已核对该候选/ }).check();
  await page.getByRole('button', { name: '批准并启用候选' }).click();
  await expect
    .poll(
      async () =>
        (
          await (
            await context.request.get('http://127.0.0.1:5374/api/v1/admin/model-settings/ai302')
          ).json()
        ).revision,
    )
    .toBe(1);
  await expect(page.getByRole('status')).toContainText('已启用版本 v1');
  await expect(page.getByLabel('文生图模型', { exact: true })).toHaveValue('gpt-image-future-test');
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue('test-vision-model');
  await expect(page.getByLabel('输出 token 上限', { exact: true })).toHaveValue('640');
  await page.reload();
  await expect(page.getByText('正在编辑当前生效配置', { exact: true })).toBeVisible();
  await expect(page.getByLabel('文生图模型', { exact: true })).toHaveValue('gpt-image-future-test');
  expect(errors).toEqual([]);
});

test('保存失败保留输入，修改视觉配置清除旧反馈，重试成功可再次编辑', async ({ page, context }) => {
  await loginAdmin(context);
  const active = await (
    await context.request.get('http://127.0.0.1:5374/api/v1/admin/model-settings/ai302')
  ).json();
  await page.goto('http://127.0.0.1:5374/models');
  await page.getByLabel('视觉模型 ID').fill('vision-retry-test');
  await page.route('**/api/v1/admin/model-candidates', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({ status: 503, json: { error: { message: '临时故障，请重试' } } });
    } else await route.continue();
  });
  await page.getByRole('button', { name: '保存为候选新版本' }).click();
  await expect(page.getByRole('alert')).toContainText('保存失败：临时故障，请重试');
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue('vision-retry-test');
  await page.getByLabel('输出 token 上限', { exact: true }).fill('768');
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.unroute('**/api/v1/admin/model-candidates');
  await page.getByRole('button', { name: '保存为候选新版本' }).click();
  await expect(page.getByRole('status')).toContainText('候选已保存');
  await page.getByLabel('输出 token 上限', { exact: true }).fill('896');
  await expect(page.getByRole('status')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '保存为候选新版本' })).toBeEnabled();
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await expect(page.getByLabel('输出 token 上限', { exact: true })).toHaveValue('768');
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue('vision-retry-test');
  await page.getByRole('button', { name: '使用当前生效配置' }).click();
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue(active.vision.model);
  await page.getByRole('button', { name: '载入配置', exact: true }).first().click();
  await expect(page.getByLabel('视觉模型 ID')).toHaveValue('vision-retry-test');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByRole('group', { name: '视觉分析 · 独立配置', exact: true })
    .screenshot({ path: '.data/model-settings-vision-desktop.png' });
  await page.screenshot({ path: '.data/model-settings-desktop.png', fullPage: true });
  await page.getByRole('button', { name: '查看 / 审核启用', exact: true }).first().click();
  await page
    .locator('#model-candidates')
    .screenshot({ path: '.data/model-settings-review-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('group', { name: '视觉分析 · 独立配置', exact: true })
    .screenshot({ path: '.data/model-settings-vision-mobile.png' });
  await page
    .locator('#model-candidates')
    .screenshot({ path: '.data/model-settings-review-mobile.png' });
  await page.screenshot({ path: '.data/model-settings-mobile.png', fullPage: true });
});

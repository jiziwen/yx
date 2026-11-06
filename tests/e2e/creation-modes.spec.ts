/** 四种正式方式使用同一草稿和唯一确认入口，验证真实素材用途和输出比例。 */
import { test, expect } from '@playwright/test';
import {
  studioProject,
  material,
  closeMaterial,
  currentPlan,
  synthetic,
  editIdea,
} from './studio-session';
for (const mobile of [false, true])
  test(`${mobile ? '窄屏' : '桌面'}四种模式完成真实交付，成片可继续编辑`, async ({ page }) => {
    if (mobile) await page.setViewportSize({ width: 390, height: 844 });
    const project = await studioProject(page);
    const canvas = page.locator('.cx-canvas');
    let count = 0;
    for (const [label, mode, roles] of [
      ['设计写真', 'portrait', ['person']],
      ['修改照片', 'edit', ['base']],
      ['文字创作', 'text', []],
      ['拍同款', 'template', ['base', 'person']],
    ] as const) {
      await page.getByRole('button', { name: '创作画面', exact: true }).click();
      if (mode === 'edit') {
        await page.getByRole('button', { name: '作品与进度', exact: true }).click();
        await canvas.getByRole('button', { name: '以此为底图继续修改' }).first().click();
      } else await canvas.getByRole('button', { name: label, exact: true }).click();
      if (mode === 'text') await page.getByLabel('你心里的画面').fill('自然的胶片静物，不包含人物');
      const confirm = canvas.getByRole('button', { name: /^确认生成/ });
      await expect(confirm).toBeEnabled();
      await expect(page.getByRole('button', { name: /^确认生成/ })).toHaveCount(1);
      expect(
        await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
      ).toHaveLength(count);
      const plan = await currentPlan(page, project.id);
      expect(plan.spec_json.mode).toBe(mode);
      expect(plan.spec_json.items[0].inputs.map((item: { role: string }) => item.role)).toEqual(
        roles,
      );
      expect(plan.spec_json.aspect_ratio_choice).toBe('auto');
      await confirm.click();
      count++;
      await expect(canvas.getByAltText('开发测试卡片', { exact: true })).toHaveCount(count, {
        timeout: 20000,
      });
      await expect(page.getByRole('button', { name: '作品与进度', exact: true })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      await expect(canvas.getByRole('button', { name: label, exact: true })).toHaveCount(0);
      await expect(canvas.getByLabel('画幅', { exact: true })).toBeHidden();
      await expect(canvas.getByRole('button', { name: /确认生成|已确认执行/ })).toHaveCount(0);
      await expect(canvas.locator('.sx-studio-status')).toBeHidden();
      await expect(canvas.locator('.sx-materials')).toBeHidden();
    }
    const thumbnail = canvas.getByRole('button', { name: '查看作品1大图', exact: true });
    const bounds = await thumbnail.boundingBox();
    expect(bounds!.height).toBeLessThanOrEqual(212);
    expect(bounds!.width).toBeLessThan(260);
    await thumbnail.click();
    const preview = page.getByRole('dialog', { name: '作品预览', exact: true });
    await expect(preview).toBeVisible();
    await expect(preview.getByRole('button', { name: '上一张作品' })).toBeDisabled();
    await expect(preview.getByAltText('作品大图 · 第1张')).toBeVisible();
    await expect(preview.getByRole('link', { name: '下载原图', exact: true })).toBeInViewport();
    await expect(
      preview.getByRole('button', { name: '以此为底图继续修改', exact: true }),
    ).toBeInViewport();
    await page.keyboard.press('ArrowRight');
    await expect(preview.getByAltText('作品大图 · 第2张')).toBeVisible();
    await page.keyboard.press('ArrowLeft');
    await expect(preview.getByAltText('作品大图 · 第1张')).toBeVisible();
    await page.screenshot({
      path: `.data/studio-results-preview-${mobile ? 'mobile' : 'desktop'}.png`,
    });
    await page.keyboard.press('Escape');
    await expect(preview).toHaveCount(0);
    await expect(thumbnail).toBeFocused();
    const like = canvas.getByRole('button', { name: '喜欢作品1', exact: true });
    await like.click();
    await page.getByRole('button', { name: '创作画面', exact: true }).click();
    await expect(canvas.getByRole('region', { name: '生成进度与作品' })).toHaveCount(0);
    await expect(canvas.getByRole('button', { name: '拍同款', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await page.getByRole('button', { name: '作品与进度', exact: true }).click();
    await expect(
      canvas.getByRole('button', { name: '取消喜欢作品1', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    await page.screenshot({
      path: `.data/studio-results-${mobile ? 'mobile' : 'desktop'}.png`,
      fullPage: true,
    });
    await page.reload();
    await expect(canvas.getByRole('button', { name: '已确认执行' })).toBeDisabled();
    expect(
      await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
    ).toHaveLength(4);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
      false,
    );
    await page.screenshot({
      path: `.data/studio-new-${mobile ? 'mobile' : 'desktop'}.png`,
      fullPage: true,
    });
  });

test('空作品页不显示创作表单和阻塞提示，切换保留草稿，聊天添加照片返回创作', async ({ page }) => {
  const project = await studioProject(page, '作品页边界', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('海边日落下的白色灯塔');
  await canvas.getByLabel('画幅', { exact: true }).selectOption('16:9');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  await page.getByRole('button', { name: '作品与进度', exact: true }).click();
  await expect(canvas.getByText('这里，等待你的第一张作品。', { exact: true })).toBeVisible();
  await expect(canvas.getByRole('combobox')).toHaveCount(0);
  await expect(canvas.getByRole('textbox')).toHaveCount(0);
  await expect(canvas.getByRole('button', { name: /确认生成|细节|文字创作/ })).toHaveCount(0);
  await expect(canvas.locator('.sx-studio-status')).toBeHidden();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(canvas.getByRole('combobox')).toHaveCount(0);
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await expect(canvas.getByLabel('你心里的画面')).toHaveValue('海边日落下的白色灯塔');
  await expect(canvas.getByLabel('画幅', { exact: true })).toHaveValue('16:9');
  await expect(canvas.getByRole('region', { name: '生成进度与作品' })).toHaveCount(0);
  await canvas.getByRole('button', { name: '修改照片', exact: true }).click();
  await expect(canvas.locator('.sx-studio-status')).toContainText('底图');
  await page.getByRole('button', { name: '作品与进度', exact: true }).click();
  await expect(canvas.locator('.sx-studio-status')).toBeHidden();
  await page.getByRole('button', { name: '添加照片', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '照片用在哪里？' })).toBeVisible();
  await closeMaterial(page);
  await expect(page.getByRole('button', { name: '创作画面', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json()).toEqual(
    [],
  );
});

test('底图上传有用途声明，默认跟随原图，手动9:16刷新后保留', async ({ page }) => {
  const project = await studioProject(page, '底图和画幅', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '修改照片', exact: true }).click();
  await material(page, '待修改照片');
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('上传修改底图')).toBeDisabled();
  await dialog.getByLabel('底图使用声明').check();
  await dialog
    .getByLabel('上传修改底图')
    .setInputFiles({ name: 'base.png', mimeType: 'image/png', buffer: synthetic });
  await expect(dialog.getByRole('button', { name: '选择项目底图 1' })).toBeVisible();
  await closeMaterial(page);
  await expect(canvas.getByAltText('本次准备修改的底图')).toBeVisible();
  await expect(canvas.getByLabel('画幅', { exact: true })).toHaveValue('auto');
  await expect(canvas.locator('.sx-output-meta')).toContainText('1:1');
  await editIdea(page, '只调整光线，保留其他部分');
  await canvas.getByLabel('画幅', { exact: true }).selectOption('9:16');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  expect((await currentPlan(page, project.id)).spec_json.items[0].aspect_ratio).toBe('9:16');
  await page.reload();
  await expect(canvas.getByLabel('画幅', { exact: true })).toHaveValue('9:16');
  await expect(canvas.locator('.sx-idea-line')).toContainText('只调整光线');
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json()).toEqual(
    [],
  );
});

test('风格参考图作为style输入，切到文字不会夹带图片；弹框Esc关闭恢复焦点', async ({ page }) => {
  const project = await studioProject(page, '风格用途');
  const canvas = page.locator('.cx-canvas');
  const trigger = canvas.getByRole('button', { name: '风格参考图（选填）', exact: true });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('风格参考使用声明').check();
  await dialog
    .getByLabel('上传风格参考图')
    .setInputFiles({ name: 'style.png', mimeType: 'image/png', buffer: synthetic });
  await expect(dialog.getByRole('button', { name: '选择风格参考 1', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  expect(
    (await currentPlan(page, project.id)).spec_json.items[0].inputs.map(
      (input: { role: string }) => input.role,
    ),
  ).toEqual(['person', 'style']);
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('紫色花园');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  expect((await currentPlan(page, project.id)).spec_json.items[0].inputs).toEqual([]);
});

test('刷新时旧提示词卡自动重建，保留画面要求和画幅且不创建任务', async ({ page }) => {
  const project = await studioProject(page, '提示词规则升级', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('大海，画面中央一位美女，不要水印');
  await canvas.getByLabel('画幅', { exact: true }).selectOption('16:9');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  const old = await currentPlan(page, project.id);
  await page.route(
    `**/api/v1/web/projects/${project.id}/plans`,
    async (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      const response = await route.fetch();
      const plans = await response.json();
      // 模拟浏览器先读到旧规则卡片；API实际冻结内容和确认接口不受此夹具修改。
      plans[0].spec_json.prompt_policy_hash = 'retired-prompt-policy';
      await route.fulfill({ response, json: plans });
    },
    { times: 1 },
  );
  await page.reload();
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  await expect.poll(async () => (await currentPlan(page, project.id)).id).not.toBe(old.id);
  await expect(canvas.getByLabel('你心里的画面')).toHaveValue('大海，画面中央一位美女，不要水印');
  await expect(canvas.getByLabel('画幅', { exact: true })).toHaveValue('16:9');
  const current = await currentPlan(page, project.id);
  const catalog = await (await page.request.get('/api/v1/web/catalog')).json();
  expect(current.spec_json.prompt_policy_hash).toBe(catalog.creation_prompt_policy_hash);
  expect(current.spec_json.notes).toContain('不要水印');
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json()).toEqual(
    [],
  );
});

test('历史三种画幅声明不再拦截9:16，任意比例和像素尺寸刷新后仍可确认', async ({ page }) => {
  await page.route('**/api/v1/web/catalog', async (route) => {
    const response = await route.fetch();
    const catalog = await response.json();
    for (const mode of catalog.creation_modes) mode.aspect_ratios = ['3:4', '4:3', '1:1'];
    await route.fulfill({ response, json: catalog });
  });
  const project = await studioProject(page, '任意尺寸', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('海边日落，画面中央一位人物');
  await canvas.getByLabel('画幅', { exact: true }).selectOption('9:16');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  expect((await currentPlan(page, project.id)).spec_json.items[0].size).toBe('864x1536');
  for (const [choice, size] of [
    ['7:5', '1022x730'],
    ['202x300', '202x300'],
  ]) {
    const path = `/api/v1/web/projects/${project.id}/studio-draft`;
    const stored = await (await page.request.get(path)).json();
    const response = await page.request.put(path, {
      data: {
        expected_revision: stored.revision,
        expected_privacy_epoch: stored.privacy_epoch,
        draft: { ...stored.draft, aspect_ratio: choice },
      },
    });
    expect(response.ok()).toBe(true);
    await page.reload();
    await expect(canvas.getByLabel('画幅', { exact: true })).toHaveValue(choice);
    await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
    expect((await currentPlan(page, project.id)).spec_json.items[0].size).toBe(size);
  }
  expect(await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json()).toEqual(
    [],
  );
});

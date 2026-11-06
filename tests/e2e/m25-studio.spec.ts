/** 双栏工作室的聊天同步、失败保留和目录选择恢复；四模式交付见creation-modes。 */
import { test, expect } from '@playwright/test';
import { material, closeMaterial, synthetic } from './studio-session';

test('纯聊天自动更新右侧方式和配置，确认前不出图', async ({ page, context }) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (
    await context.request.post('/api/v1/web/auth/code', { data: { phone } })
  ).json();
  await context.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  const project = await (
    await context.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title: '明确聊天修改验收', kind: 'portrait' },
    })
  ).json();
  await context.request.post(`/api/v1/web/projects/${project.id}/trial-grants`);
  await page.goto(`/projects/${project.id}/studio`);
  await expect(page.getByLabel('给 Lumi 留言')).toBeEnabled();
  await page.getByRole('button', { name: '作品与进度', exact: true }).click();
  await page.getByLabel('给 Lumi 留言').fill('测试明确修改：月光下的紫色花园');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  const chat = page.locator('.dp-chat');
  await expect(chat.locator('.dp-message-you > div').first()).toHaveCSS(
    'background-color',
    'rgba(0, 0, 0, 0)',
  );
  await expect(chat.locator('.dp-message-you > div').first()).toHaveCSS('padding', '0px');
  await chat.screenshot({ path: '.data/studio-chat-single-bubble.png' });
  await expect(chat.locator('.cx-creation-pane')).toHaveCount(0);
  await expect(chat.getByRole('button', { name: /^确认生成/ })).toHaveCount(0);
  await expect(
    chat.locator('.at-guide-mode, .cx-chat-memory, .cx-vision-picker, .cx-chat-technical'),
  ).toHaveCount(0);
  await expect(chat.getByText('对话模型', { exact: false })).toHaveCount(0);
  await expect(
    page.locator('.cx-canvas').getByRole('button', { name: '文字创作', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toHaveCount(0);
  await expect(page.locator('.cx-canvas').getByLabel('你心里的画面')).toHaveValue(
    /月光下的紫色花园/,
  );
  await expect(
    page.locator('.sx-generate-row').getByRole('button', { name: /^确认生成/ }),
  ).toBeEnabled();
  await page.locator('.sx-generate-row').scrollIntoViewIfNeeded();
  await expect(page.locator('.sx-generate-row')).toBeInViewport();
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(0);
  const buttons = page.getByRole('button', { name: /^确认生成/ });
  await buttons.first().click();
  await expect(page.getByRole('region', { name: '生成进度与作品' })).toBeVisible();
  await expect(page.getByRole('button', { name: /确认生成|已确认执行/ })).toHaveCount(0);
  await page.getByRole('button', { name: '创作画面', exact: true }).click();
  await expect(
    page.locator('.cx-canvas').getByRole('button', { name: '已确认执行', exact: true }),
  ).toBeDisabled();
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(1);
});

test('方案被拒绝时仍保留生成入口和明确原因', async ({ page, context }) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (
    await context.request.post('/api/v1/web/auth/code', { data: { phone } })
  ).json();
  await context.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  const project = await (
    await context.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title: '拒绝方案可见入口', kind: 'portrait' },
    })
  ).json();
  await page.route('**/api/v1/web/projects/*/plans', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'TEMPLATE_NOT_RELEASED', message: '样片尚未审核，请更换输入' },
      }),
    });
  });
  await page.goto(`/projects/${project.id}/studio`);
  await page.locator('.cx-canvas').getByRole('button', { name: '文字创作', exact: true }).click();
  await page.getByLabel('你心里的画面').fill('测试静物，不包含人物');
  const dock = page.locator('.sx-generate-row');
  // section 有可访问名称时作为 region。
  await expect(dock.getByRole('button', { name: /^确认生成/ })).toBeVisible();
  await expect(dock.getByRole('button', { name: /^确认生成/ })).toBeDisabled();
  await expect(page.locator('.sx-studio-status')).toContainText('样片尚未审核，请更换输入');
  await dock.scrollIntoViewIfNeeded();
  await expect(dock).toBeInViewport();
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(0);
});

for (const mode of ['portrait', 'template'] as const) {
  test(`聊天按右侧图库编号替换${mode}参考，保留人物且刷新恢复`, async ({ page, context }) => {
    const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
    const code = await (
      await context.request.post('/api/v1/web/auth/code', { data: { phone } })
    ).json();
    await context.request.post('/api/v1/web/auth/login', {
      data: { phone, code: code.debug_code },
    });
    let project = await (
      await context.request.post('/api/v1/web/projects', {
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        data: { title: '图库切换合成验收', kind: 'portrait' },
      })
    ).json();
    const subject = await (
      await context.request.post(`/api/v1/web/projects/${project.id}/subjects`, {
        data: { subject_key: 'person_a', display_name: '合成人物', declared: true },
      })
    ).json();
    const asset = await (
      await context.request.post(`/api/v1/web/projects/${project.id}/uploads`, {
        multipart: {
          subject_id: subject.id,
          file: { name: 'synthetic.png', mimeType: 'image/png', buffer: synthetic },
        },
      })
    ).json();
    project = await (await context.request.get(`/api/v1/web/projects/${project.id}`)).json();
    const catalog = await (await context.request.get('/api/v1/web/catalog')).json();
    const style = catalog.styles.find((item: { id: string }) => item.id === 'portrait_portrait_01');
    const field = mode === 'portrait' ? 'style_shot_ids' : 'shot_ids';
    const initial = {
      mode,
      style_id: style.id,
      aspect_ratio: '3:4',
      count: 1,
      variants: 1,
      mood: '柔光',
      notes: '保留人物和服装',
      change: '',
      keep: [],
      reference_asset_ids: [asset.id],
      base_asset_id: null,
      shot_ids: [],
      style_shot_ids: [],
      positions: { [subject.id]: 'only' },
      [field]: [style.shots[0].id],
    };
    const saved = await context.request.put(`/api/v1/web/projects/${project.id}/studio-draft`, {
      data: { expected_revision: 0, expected_privacy_epoch: project.privacy_epoch, draft: initial },
    });
    expect(saved.ok()).toBeTruthy();
    await page.goto(`/projects/${project.id}/studio`);
    const prefix = mode === 'portrait' ? '使用风格参考' : '使用底图';
    const picker = mode === 'portrait' ? '风格参考图（选填）' : '样片底图';
    await material(page, picker);
    await expect(page.getByRole('button', { name: `${prefix} 1`, exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await closeMaterial(page);
    await page.getByLabel('给 Lumi 留言').fill('测试目录切换：风格参考换成第二张，第一张不要了');
    await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
    await material(page, picker);
    await expect(page.getByRole('button', { name: `${prefix} 2`, exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(page.getByRole('button', { name: `${prefix} 1`, exact: true })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    await closeMaterial(page);
    await expect(page.getByRole('button', { name: '采用这个建议', exact: true })).toHaveCount(0);
    await expect
      .poll(
        async () =>
          (
            await (
              await context.request.get(`/api/v1/web/projects/${project.id}/studio-draft`)
            ).json()
          ).draft[field],
      )
      .toEqual([style.shots[1].id]);
    await page.reload();
    await material(page, picker);
    await expect(page.getByRole('button', { name: `${prefix} 2`, exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await closeMaterial(page);
    const persisted = (
      await (await context.request.get(`/api/v1/web/projects/${project.id}/studio-draft`)).json()
    ).draft;
    expect(persisted.mode).toBe(mode);
    expect(persisted.reference_asset_ids).toEqual([asset.id]);
    expect(persisted.notes).toBe(initial.notes);
    expect(
      await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
    ).toHaveLength(0);
    await page.screenshot({ path: `.data/catalog-selection-${mode}.png`, fullPage: true });
  });
}

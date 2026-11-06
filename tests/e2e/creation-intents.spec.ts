/** 真实草稿与Agent路径验证跨方式切换；合成素材、本地插件、确认前无出图。 */
import { material, closeMaterial } from './studio-session';
import { test, expect } from '@playwright/test';
const synthetic = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAABMklEQVR4nO3TMREAIBDEwAf/dnCAB+wgY5usgSsyt949E2fD7RTA6wFYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACjDWB0PEA1B5pEqSAAAAAElFTkSuQmCC',
  'base64',
);

test('只替换人物切拍同款并保留已选第二张，聊天自由切回写真/文字/编辑，仍需确认', async ({
  page,
  context,
}) => {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (
    await context.request.post('/api/v1/web/auth/code', { data: { phone } })
  ).json();
  await context.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  let project = await (
    await context.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title: '换人和自由创作验收', kind: 'portrait' },
    })
  ).json();
  await context.request.post(`/api/v1/web/projects/${project.id}/trial-grants`);
  const subject = await (
    await context.request.post(`/api/v1/web/projects/${project.id}/subjects`, {
      data: { subject_key: 'person_a', display_name: '测试人物', declared: true },
    })
  ).json();
  const person = await (
    await context.request.post(`/api/v1/web/projects/${project.id}/uploads`, {
      multipart: {
        subject_id: subject.id,
        file: { name: 'person.png', mimeType: 'image/png', buffer: synthetic },
      },
    })
  ).json();
  const base = await (
    await context.request.post(`/api/v1/web/projects/${project.id}/uploads`, {
      multipart: {
        purpose: 'base',
        declared: 'true',
        file: { name: 'base.png', mimeType: 'image/png', buffer: synthetic },
      },
    })
  ).json();
  project = await (await context.request.get(`/api/v1/web/projects/${project.id}`)).json();
  expect(
    (
      await context.request.put(`/api/v1/web/projects/${project.id}/studio-draft`, {
        data: {
          expected_revision: 0,
          expected_privacy_epoch: project.privacy_epoch,
          draft: {
            mode: 'portrait',
            subject_only: false,
            style_id: 'portrait_portrait_01',
            aspect_ratio: '3:4',
            count: 1,
            variants: 1,
            mood: '更暖的色调',
            notes: '重新设计场景，调暖一点',
            change: '',
            keep: [],
            reference_asset_ids: [person.id],
            base_asset_id: base.id,
            shot_ids: ['scene'],
            style_shot_ids: ['portrait'],
            positions: { [subject.id]: 'only' },
          },
        },
      })
    ).ok(),
  ).toBeTruthy();
  await page.goto(`/projects/${project.id}/studio`);
  const pane = page.locator('.cx-canvas');
  async function chat(text: string, modeLabel: string) {
    await page.getByLabel('给 Lumi 留言').fill(text);
    await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
    await expect(pane.getByRole('button', { name: modeLabel, exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(pane.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
    expect(
      await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
    ).toEqual([]);
  }
  await chat('把人物替换就行了', '拍同款');
  await material(page, '细节');
  await expect(pane.getByLabel('只替换人物，保留底图其他细节')).toBeChecked();
  await closeMaterial(page);
  await material(page, '样片底图');
  await expect(pane.getByRole('button', { name: '使用底图 2', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(pane.getByRole('button', { name: '使用底图 1', exact: true })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await closeMaterial(page);
  await expect(pane.locator('.sx-idea-line')).toContainText('保留底图站位、姿势、构图和色调');
  const first = (
    await (await context.request.get(`/api/v1/web/projects/${project.id}/plans`)).json()
  )[0];
  expect(first.spec_json.items[0].inputs.map((input: { role: string }) => input.role)).toEqual([
    'base',
    'person',
  ]);
  expect(first.spec_json.items[0].inputs[0].shot_id).toBe('portrait');
  expect(first.spec_json.subject_only).toBe(true);
  await page.screenshot({ path: '.data/subject-only-studio-e2e.png', fullPage: true });
  await chat('测试自由切换：设计写真', '设计写真');
  await material(page, '风格参考图（选填）');
  await expect(pane.getByRole('button', { name: '使用风格参考 2', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await closeMaterial(page);
  await chat('测试自由切换：文字创作', '文字创作');
  const textPlan = (
    await (await context.request.get(`/api/v1/web/projects/${project.id}/plans`)).json()
  )[0];
  expect(textPlan.spec_json.items[0].inputs).toEqual([]);
  await chat('测试自由切换：修改照片', '修改照片');
  const editPlan = (
    await (await context.request.get(`/api/v1/web/projects/${project.id}/plans`)).json()
  )[0];
  expect(editPlan.spec_json.base_asset_id).toBe(base.id);
  expect(editPlan.spec_json.items[0].inputs.map((input: { role: string }) => input.role)).toEqual([
    'base',
  ]);
  // 右侧切换也使用相同迁移规则，不能丢掉曾选的第二张目录图。
  await pane.getByRole('button', { name: '设计写真', exact: true }).click();
  await material(page, '风格参考图（选填）');
  await expect(pane.getByRole('button', { name: '使用风格参考 2', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await closeMaterial(page);
  await chat('只替换人物', '拍同款');
  await page.reload();
  await material(page, '细节');
  await expect(pane.getByLabel('只替换人物，保留底图其他细节')).toBeChecked();
  await closeMaterial(page);
  await material(page, '样片底图');
  await expect(pane.getByRole('button', { name: '使用底图 2', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await closeMaterial(page);
  await expect(pane.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toEqual([]);
  await pane.getByRole('button', { name: /^确认生成/ }).click();
  await expect(pane.getByAltText('开发测试卡片', { exact: true })).toHaveCount(1, {
    timeout: 20000,
  });
  expect(
    await (await context.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(1);
});

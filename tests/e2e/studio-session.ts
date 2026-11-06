/** 正式工作室验收共用入口；素材为合成图，不访问付费供应商。 */
import { expect, type Page } from '@playwright/test';
export const synthetic = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAIAAABMXPacAAABMklEQVR4nO3TMREAIBDEwAf/dnCAB+wgY5usgSsyt949E2fD7RTA6wFYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACoAVACsAVgCsAFgBsAJgBcAKgBUAKwBWAKwAWAGwAmAFwAqAFQArAFYArABYAbACYAXACjDWB0PEA1B5pEqSAAAAAElFTkSuQmCC',
  'base64',
);
export async function studioProject(page: Page, title = '双栏工作室验收', people = true) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await (await page.request.post('/api/v1/web/auth/code', { data: { phone } })).json();
  await page.request.post('/api/v1/web/auth/login', { data: { phone, code: code.debug_code } });
  const project = await (
    await page.request.post('/api/v1/web/projects', {
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      data: { title, kind: 'portrait' },
    })
  ).json();
  await page.request.post(`/api/v1/web/projects/${project.id}/trial-grants`);
  if (people) {
    const subject = await (
      await page.request.post(`/api/v1/web/projects/${project.id}/subjects`, {
        data: { subject_key: 'person_a', display_name: '合成 A', declared: true },
      })
    ).json();
    await page.request.post(`/api/v1/web/projects/${project.id}/uploads`, {
      multipart: {
        subject_id: subject.id,
        file: { name: 'fixture.png', mimeType: 'image/png', buffer: synthetic },
      },
    });
  }
  await page.goto(`/projects/${project.id}/studio`);
  await expect(page.locator('.sx-modes button')).toHaveCount(4);
  if (people) {
    await material(page, '人物参考');
    await page
      .getByRole('dialog')
      .getByRole('button', { name: '选择参考照片：合成 A 1', exact: true })
      .click();
    await closeMaterial(page);
  }
  return project;
}
export async function material(page: Page, name: string) {
  await page.locator('.cx-canvas').getByRole('button', { name, exact: true }).click();
  return page.getByRole('dialog');
}
export async function closeMaterial(page: Page) {
  await page.getByRole('dialog').getByRole('button', { name: '完成', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
}
export async function editIdea(page: Page, text: string) {
  await material(page, '编辑创意');
  await page.getByRole('dialog').locator('textarea').fill(text);
  await closeMaterial(page);
}
export async function currentPlan(page: Page, projectId: string) {
  return (await (await page.request.get(`/api/v1/web/projects/${projectId}/plans`)).json())[0];
}

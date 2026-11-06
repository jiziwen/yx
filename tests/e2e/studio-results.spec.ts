/** 模拟任务读到旧列表、作品晚一次可见，验证无需刷新即可交付和继续修改。 */
import { expect, test } from '@playwright/test';
import { currentPlan, studioProject } from './studio-session';

test('短暂旧任务列表和迟到作品自动补齐，大图操作关闭弹框并聚焦聊天', async ({ page }) => {
  const project = await studioProject(page, '作品自动同步', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('清晨的海面与白色灯塔');
  await canvas.getByLabel('成片张数', { exact: true }).selectOption('2');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  let hidJobs = false;
  let hidFinalWork = false;
  let workReads = 0;
  await page.route(`**/api/v1/web/projects/${project.id}/jobs`, async (route) => {
    const response = await route.fetch();
    const jobs = await response.json();
    if (jobs.length && !hidJobs) {
      hidJobs = true;
      return route.fulfill({ response, json: [] });
    }
    await route.fulfill({ response, json: jobs });
  });
  await page.route(`**/api/v1/web/projects/${project.id}/works`, async (route) => {
    workReads++;
    const response = await route.fetch();
    const works = await response.json();
    if (works.length === 2 && !hidFinalWork) {
      hidFinalWork = true;
      return route.fulfill({ response, json: works.slice(0, 1) });
    }
    await route.fulfill({ response, json: works });
  });
  await canvas.getByRole('button', { name: /^确认生成/ }).click();
  await expect(canvas.getByAltText('开发测试卡片', { exact: true })).toHaveCount(2, {
    timeout: 25000,
  });
  expect(hidJobs).toBe(true);
  expect(hidFinalWork).toBe(true);
  expect(workReads).toBeGreaterThan(1);
  await expect
    .poll(() =>
      canvas
        .getByAltText('开发测试卡片', { exact: true })
        .evaluateAll((images) =>
          images.every(
            (image) =>
              (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
          ),
        ),
    )
    .toBe(true);
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toHaveCount(0);
  await canvas.getByRole('button', { name: '查看作品1大图', exact: true }).click();
  const preview = page.getByRole('dialog', { name: '作品预览', exact: true });
  const source = await preview.getByAltText('作品大图 · 第1张').getAttribute('src');
  await preview.getByRole('button', { name: '和 Lumi 聊这张', exact: true }).click();
  await expect(preview).toHaveCount(0);
  await expect(page.getByLabel('给 Lumi 留言')).toBeFocused();
  await expect(canvas.getByRole('button', { name: '修改照片', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(canvas.getByAltText('本次准备修改的底图')).toHaveAttribute('src', source!);
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  const plan = await currentPlan(page, project.id);
  expect(plan.spec_json.mode).toBe('edit');
  const jobs = await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json();
  expect(jobs).toHaveLength(2);
  expect(jobs.every((job: { status: string }) => job.status === 'succeeded')).toBe(true);
});

test('成图获取阶段仍自动刷新，不显示成失败；核对完成后自动补图', async ({ page }) => {
  const project = await studioProject(page, '成图获取阶段', false);
  const canvas = page.locator('.cx-canvas');
  await canvas.getByRole('button', { name: '文字创作', exact: true }).click();
  await canvas.getByLabel('你心里的画面').fill('傍晚的海面与云层');
  await expect(canvas.getByRole('button', { name: /^确认生成/ })).toBeEnabled();
  let exposedReconciliation = false;
  let recovered = false;
  await page.route(`**/api/v1/web/projects/${project.id}/jobs`, async (route) => {
    const response = await route.fetch();
    const jobs = await response.json();
    if (jobs.length && !exposedReconciliation) {
      exposedReconciliation = true;
      return route.fulfill({
        response,
        json: jobs.map((job: { id: string }) => ({
          ...job,
          status: 'reconciliation_required',
          error_code: 'PROVIDER_RESULT_UNAVAILABLE',
        })),
      });
    }
    if (jobs.some((job: { status: string }) => job.status === 'succeeded')) recovered = true;
    await route.fulfill({ response, json: jobs });
  });
  await page.route(`**/api/v1/web/projects/${project.id}/works`, async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: recovered ? await response.json() : [] });
  });
  await canvas.getByRole('button', { name: /^确认生成/ }).click();
  await expect(
    canvas.getByLabel('正在处理的任务').getByText('正在获取生成结果', { exact: true }),
  ).toBeVisible();
  await expect(canvas.getByText(/张未完成/)).toHaveCount(0);
  await expect(canvas.getByAltText('开发测试卡片', { exact: true })).toHaveCount(1, {
    timeout: 20000,
  });
  expect(exposedReconciliation).toBe(true);
  expect(recovered).toBe(true);
  expect(
    await (await page.request.get(`/api/v1/web/projects/${project.id}/jobs`)).json(),
  ).toHaveLength(1);
});

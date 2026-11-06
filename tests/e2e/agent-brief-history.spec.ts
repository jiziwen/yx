/** 需求卡明确确认、长历史翻页、按需来源与遗忘保护；夹具仅写隔离测试数据库。 */
import { test, expect, type Page, type BrowserContext, type TestInfo } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { resolve, sep } from 'node:path';

async function enter(page: Page, context: BrowserContext) {
  const phone = '139' + String(Math.floor(Math.random() * 1e8)).padStart(8, '0');
  const code = await context.request.post('/api/v1/web/auth/code', { data: { phone } });
  await context.request.post('/api/v1/web/auth/login', {
    data: { phone, code: (await code.json()).debug_code },
  });
  const response = await context.request.post('/api/v1/web/projects', {
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    data: { title: '创作需求与历史验收', kind: 'portrait' },
  });
  const { id } = await response.json();
  await page.goto(`/projects/${id}/studio`);
  await expect(page.getByLabel('给 Lumi 留言')).toBeEnabled();
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  return id as string;
}

function seed(info: TestInfo, id: string, turns: number) {
  const path = info.config.metadata.databasePath;
  if (
    typeof path !== 'string' ||
    !resolve(path).startsWith(resolve('.data/e2e') + sep) ||
    !path.includes('run-')
  )
    throw new Error('历史夹具只允许写隔离 E2E 数据库');
  const result = spawnSync(
    'uv',
    [
      'run',
      'python',
      '-c',
      `
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path("tests").resolve()))
from test_brief_history import seed_history
from app.core.config import Settings
from app.main import create_app
from app.modules.projects.models import Project
app=create_app(Settings(app_env="test",storage_root=Path(os.environ["HISTORY_FIXTURE_DB"]).parent/"objects"))
with app.state.sessions() as db:
 p=db.get(Project,os.environ["HISTORY_FIXTURE_PROJECT"])
 assert p is not None
 project={"id":p.id,"brief_revision":p.brief_revision,"privacy_epoch":p.privacy_epoch}
seed_history(app,project,turns=int(os.environ["HISTORY_FIXTURE_TURNS"]))
app.state.engine.dispose()
`,
    ],
    {
      cwd: resolve('services/backend'),
      encoding: 'utf8',
      env: {
        ...process.env,
        DATABASE_URL: 'sqlite:///' + path,
        HISTORY_FIXTURE_DB: path,
        HISTORY_FIXTURE_PROJECT: id,
        HISTORY_FIXTURE_TURNS: String(turns),
      },
    },
  );
  if (result.status !== 0) throw new Error(result.stderr);
}

test('需求卡建议明确确认才保存，多窗口编辑不覆盖新版本，图片仍未生成', async ({
  page,
  context,
}) => {
  const id = await enter(page, context);
  await page
    .getByLabel('给 Lumi 留言')
    .fill('整理需求卡：场景=海边；光线=自然柔光；禁止项=不要头纱');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.getByRole('button', { name: '确认保存需求卡', exact: true })).toBeVisible();
  const path = `/api/v1/web/projects/${id}/memory`;
  expect((await (await context.request.get(path)).json()).fields).toEqual({});
  await page.getByRole('button', { name: '确认保存需求卡', exact: true }).click();
  await page.reload();
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  await page.getByText('创作需求卡 · 3 项已确认').click();
  await expect(page.getByLabel('已确认创作需求')).toContainText('自然柔光');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '管理项目记忆', exact: true }).click();
  await page.getByLabel('需求卡光线', { exact: true }).fill('我未确认的新光线');
  const memory = await (await context.request.get(path)).json();
  await context.request.put(path, {
    data: {
      expected_revision: memory.revision,
      expected_privacy_epoch: memory.privacy_epoch,
      requirements: memory.requirements,
      fields: { ...memory.fields, lighting: '另一窗口的柔和光线' },
    },
  });
  await expect(page.getByText('项目记忆已在其他页面更新，请载入最新内容后再编辑。')).toBeVisible({
    timeout: 12000,
  });
  await expect(page.getByLabel('需求卡光线', { exact: true })).toHaveValue('我未确认的新光线');
  await expect(page.getByRole('button', { name: '确认保存记忆', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '载入最新记忆', exact: true }).click();
  await expect(page.getByLabel('需求卡光线', { exact: true })).toHaveValue('另一窗口的柔和光线');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.getByRole('button', { name: '确认保存记忆', exact: true }).click();
  expect(await (await context.request.get(`/api/v1/web/projects/${id}/plans`)).json()).toEqual([]);
  expect(await (await context.request.get(`/api/v1/web/projects/${id}/jobs`)).json()).toEqual([]);
});

test('超过60条消息可翻到开头，实时新回复不丢已加载的旧页', async ({ page, context }, info) => {
  const id = await enter(page, context);
  seed(info, id, 40);
  await page.reload();
  await expect(page.locator('.dp-message-you')).toHaveCount(30);
  await page.getByRole('button', { name: '查看更早的对话', exact: true }).click();
  await expect(page.locator('.dp-message-you')).toHaveCount(40);
  await expect
    .poll(() => page.locator('.dp-chat-log').evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0);
  const position = await page.locator('.dp-chat-log').evaluate((element) => ({
    top: element.scrollTop,
    max: element.scrollHeight - element.clientHeight,
  }));
  expect(position.top).toBeLessThan(position.max - 100);
  await expect(page.getByText('很久以前的纸鸢星球第1次想法', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '查看更早的对话', exact: true })).toHaveCount(0);
  await page.getByLabel('给 Lumi 留言').fill('保留自然光，继续整理');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(page.locator('.sx-suggestion')).toBeVisible();
  await expect(page.locator('.dp-message-you')).toHaveCount(41);
  await expect(page.getByText('很久以前的纸鸢星球第1次想法', { exact: true })).toHaveCount(1);
});

test('历史工具显示原话来源，删除需求后旧记录不再供 Agent 查询', async ({ page, context }, info) => {
  const id = await enter(page, context);
  seed(info, id, 4);
  await page.getByLabel('给 Lumi 留言').fill('查询项目历史：纸鸢星球');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  const cards = page.locator('.at-tool-fact').filter({ hasText: '查询项目历史原话' });
  await expect(cards.last()).toContainText('很久以前的纸鸢星球');
  await expect(cards.last()).toContainText('仅用于回溯，以当前确认要求为准');
  const path = `/api/v1/web/projects/${id}/memory`;
  await context.request.put(path, {
    data: {
      expected_revision: 0,
      expected_privacy_epoch: 0,
      requirements: [],
      fields: { scene: '纸鸢星球' },
    },
  });
  await context.request.put(path, {
    data: { expected_revision: 1, expected_privacy_epoch: 0, requirements: [], fields: {} },
  });
  await page.reload();
  await page.getByRole('button', { name: '记忆与分析', exact: true }).click();
  await expect(page.getByLabel('给 Lumi 留言')).toBeEnabled();
  await expect(page.getByText('创作需求卡 · 0 项已确认')).toBeVisible();
  await page.getByLabel('给 Lumi 留言').fill('查询项目历史：纸鸢星球');
  await page.getByRole('button', { name: '发送给 Lumi', exact: true }).click();
  await expect(cards).toHaveCount(2);
  await expect(cards.last()).toContainText('可供回溯的记录中没有匹配原话');
  expect((await (await context.request.get(path)).json()).fields).toEqual({});
});

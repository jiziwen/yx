/** M0 一键验收：失败即停止并记录结果；需要 Docker 与已安装的 Playwright Chromium。 */
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
const startedAt = new Date().toISOString();
const milestone = process.argv.includes('--m25')
  ? 'M2.5'
  : process.argv.includes('--m2')
    ? 'M2'
    : process.argv.includes('--m1')
      ? 'M1'
      : 'M0';
const results = [];
const steps = [
  'lint',
  'typecheck',
  'api:check',
  'test',
  'test:client',
  'eval:prepare',
  'test:postgres',
  'test:redis',
  'test:e2e',
  'build',
];
if (milestone !== 'M0') steps.splice(6, 0, 'eval:preflight');
if (milestone === 'M2' || milestone === 'M2.5') steps.splice(7, 0, 'eval:m2');
const reportDir = `.data/${milestone.toLowerCase()}`;
mkdirSync(reportDir, { recursive: true });
for (const step of steps) {
  console.log(`\n[${milestone}] ${step}`);
  const started = Date.now();
  const run = spawnSync('pnpm', ['run', step], {
    stdio: 'inherit',
    env: { ...process.env, PYTHONUTF8: '1' },
  });
  results.push({
    step,
    status: run.status === 0 ? 'passed' : 'failed',
    duration_ms: Date.now() - started,
  });
  writeFileSync(
    `${reportDir}/last-run.json`,
    JSON.stringify(
      {
        schema_version: 1,
        milestone,
        scope: 'engineering_contracts_only',
        provider_quality_approved: false,
        started_at: startedAt,
        finished_at: new Date().toISOString(),
        passed:
          results.every((value) => value.status === 'passed') && results.length === steps.length,
        results,
      },
      null,
      2,
    ) + '\n',
  );
  if (run.status !== 0) process.exit(run.status ?? 1);
}
console.log(`${milestone} 工程契约验收全部通过。真实供应商质量、费用和生产接入须独立验收。`);

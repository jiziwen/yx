/** M0 代码质量入口：格式、Python 语法/导入/说明；TypeScript 额外检查未使用符号。 */
import { spawnSync } from 'node:child_process';
const steps = [
  [
    'pnpm',
    [
      'exec',
      'prettier',
      '--check',
      'apps/**/*.{ts,tsx,css,json}',
      'packages/api-client/src/index.ts',
      'packages/api-client/src/contract-type-test.ts',
      'packages/api-client/tests/*.ts',
      'scripts/*.mjs',
      'tests/e2e/*.ts',
      'playwright.config.ts',
      'tsconfig.tools.json',
      'package.json',
      'tsconfig.base.json',
      'pnpm-workspace.yaml',
    ],
    '.',
  ],
  ['uv', ['run', 'ruff', 'check', '.'], 'services/backend'],
  ['uv', ['run', 'ruff', 'format', '--check', '.'], 'services/backend'],
];
for (const [program, args, cwd] of steps) {
  const result = spawnSync(program, args, {
    cwd,
    stdio: 'inherit',
    env: { ...process.env, PYTHONUTF8: '1' },
  });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

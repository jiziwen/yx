/** 从后端 OpenAPI 生成唯一客户端类型；--check 用于 CI 检查契约漂移。 */
import { spawnSync } from 'node:child_process';
import { writeFileSync, readFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const temp = mkdtempSync(join(tmpdir(), 'yingxu-api-'));
try {
  const result = spawnSync('uv', ['run', 'python', '-m', 'app.export_openapi'], {
    cwd: 'services/backend',
    encoding: 'utf8',
    env: { ...process.env, PYTHONUTF8: '1' },
  });
  if (result.status !== 0) throw new Error(result.stderr);
  writeFileSync(join(temp, 'openapi.json'), result.stdout);
  const generated = spawnSync(
    'pnpm',
    ['exec', 'openapi-typescript', join(temp, 'openapi.json'), '-o', join(temp, 'generated.ts')],
    { encoding: 'utf8' },
  );
  if (generated.status !== 0) throw new Error(generated.stderr);
  const content = readFileSync(join(temp, 'generated.ts'), 'utf8');
  const target = 'packages/api-client/src/generated.ts';
  if (process.argv.includes('--check')) {
    if (readFileSync(target, 'utf8') !== content)
      throw new Error('API 契约已变化，请运行 pnpm api:generate 并提交生成结果');
  } else writeFileSync(target, content);
  console.log('API contract verified');
} finally {
  rmSync(temp, { recursive: true, force: true });
}

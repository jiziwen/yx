/** 临时 PostgreSQL 契约验证；只管理自己创建的容器，结束后必定清理。 */
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
const name = 'yingxu-contract-' + randomUUID().slice(0, 8);
/** 执行有界 CLI，只输出测试结果，不打印连接字符串。 */
function command(program, args, options = {}) {
  const result = spawnSync(program, args, { encoding: 'utf8', timeout: 120000, ...options });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout || program + ' failed');
  return result.stdout.trim();
}
try {
  command('docker', [
    'run',
    '--rm',
    '-d',
    '--name',
    name,
    '-e',
    'POSTGRES_USER=yingxu',
    '-e',
    'POSTGRES_PASSWORD=local-contract-only',
    '-e',
    'POSTGRES_DB=yingxu',
    '-p',
    '127.0.0.1::5432',
    'pgvector/pgvector:pg18',
  ]);
  command('docker', [
    'exec',
    name,
    'sh',
    '-c',
    'for i in 1 2 3 4 5 6 7 8 9 10; do pg_isready -U yingxu && exit 0; sleep 1; done; exit 1',
  ]);
  const port = command('docker', ['port', name, '5432/tcp']).split(':').at(-1);
  const env = {
    ...process.env,
    PYTHONUTF8: '1',
    DATABASE_URL: `postgresql+psycopg://yingxu:local-contract-only@127.0.0.1:${port}/yingxu`,
  };
  const result = spawnSync(
    'uv',
    ['run', 'python', resolve('scripts/test_postgres.py'), ...process.argv.slice(2)],
    {
      cwd: 'services/backend',
      env,
      stdio: 'inherit',
      timeout: 240000,
    },
  );
  if (result.status !== 0) process.exitCode = 1;
} finally {
  spawnSync('docker', ['rm', '-f', name], { stdio: 'ignore', timeout: 15000 });
}

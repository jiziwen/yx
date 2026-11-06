/** 临时 Redis 认证契约验收；只清理本脚本创建的容器，不访问用户已有 Redis。 */
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
const name = 'yingxu-auth-contract-' + randomUUID().slice(0, 8);
/** 仅输出错误，不将临时连接配置混入验收报告。 */
function command(program, args) {
  const result = spawnSync(program, args, { encoding: 'utf8', timeout: 120000 });
  if (result.status !== 0) throw new Error(result.stderr || result.stdout);
  return result.stdout.trim();
}
try {
  command('docker', [
    'run',
    '--rm',
    '-d',
    '--name',
    name,
    '-p',
    '127.0.0.1::6379',
    'redis:7.4-alpine',
  ]);
  command('docker', [
    'exec',
    name,
    'sh',
    '-c',
    'for i in 1 2 3 4 5 6 7 8 9 10; do redis-cli ping && exit 0; sleep 1; done; exit 1',
  ]);
  const port = command('docker', ['port', name, '6379/tcp']).split(':').at(-1);
  const run = spawnSync('uv', ['run', 'pytest', 'tests/test_redis_auth.py', '-q'], {
    cwd: 'services/backend',
    stdio: 'inherit',
    env: { ...process.env, PYTHONUTF8: '1', YINGXU_TEST_REDIS_URL: `redis://127.0.0.1:${port}/0` },
    timeout: 120000,
  });
  process.exitCode = run.status ?? 1;
} finally {
  spawnSync('docker', ['rm', '-f', name], { stdio: 'ignore', timeout: 15000 });
}

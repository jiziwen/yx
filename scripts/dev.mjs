/** 本地联调：端口检查后迁移，再启动独立进程；测试可指定端口和隔离数据库。 */
import { spawn, spawnSync } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(root, 'services/backend');
/** 非法端口立即报错，避免测试流量误发到其他项目。 */
function port(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isInteger(value) || value < 1024 || value > 65535)
    throw new Error(`${name} 端口无效`);
  return value;
}
const webPort = port('YINGXU_WEB_PORT', 5273),
  adminPort = port('YINGXU_ADMIN_PORT', 5274),
  apiPort = port('YINGXU_API_PORT', 8100);
if (new Set([webPort, adminPort, apiPort]).size !== 3)
  throw new Error('Web、Admin、API 端口必须互不相同');
const env = {
  ...process.env,
  PYTHONUTF8: '1',
  PYTHONUNBUFFERED: '1',
  YINGXU_API_PORT: String(apiPort),
  ALLOWED_ORIGINS:
    process.env.ALLOWED_ORIGINS ??
    JSON.stringify([
      `http://127.0.0.1:${webPort}`,
      `http://127.0.0.1:${adminPort}`,
      `http://localhost:${webPort}`,
      `http://localhost:${adminPort}`,
    ]),
};
const children = [];
let stopping = false;
/** 只停止本次启动的进程组，不触碰用户已有服务。 */
async function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  const signal = (child, kind) => {
    try {
      process.kill(process.platform === 'win32' ? child.pid : -child.pid, kind);
    } catch {}
  };
  const alive = (child) => {
    try {
      process.kill(process.platform === 'win32' ? child.pid : -child.pid, 0);
      return true;
    } catch {
      return false;
    }
  };
  for (const child of children) signal(child, 'SIGTERM');
  const deadline = Date.now() + 3500;
  while (children.some(alive) && Date.now() < deadline)
    await new Promise((resolve) => setTimeout(resolve, 50));
  for (const child of children) if (alive(child)) signal(child, 'SIGKILL');
  process.exit(code);
}
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
/** 在任何迁移副作用前检查端口占用，报告后直接退出。 */
async function available(value) {
  await new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', () =>
      reject(new Error(`端口 ${value} 已占用，请设置 YINGXU_*_PORT；不会停止原服务`)),
    );
    server.listen(value, '127.0.0.1', () => server.close(resolve));
  });
}
try {
  for (const value of [webPort, adminPort, apiPort]) await available(value);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}
for (const args of [
  ['sync', '--frozen'],
  ['run', 'alembic', 'upgrade', 'head'],
]) {
  const result = spawnSync('uv', args, { cwd: backend, env, stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
/** 每个子进程拥有独立组，Ctrl+C 可以收回 Vite/Python 的孙进程。 */
function start(name, command, args, cwd) {
  const child = spawn(command, args, {
    cwd,
    env,
    stdio: 'inherit',
    detached: process.platform !== 'win32',
  });
  children.push(child);
  child.on('error', (error) => {
    console.error(name, error.message);
    stop(1);
  });
  child.on('exit', (code) => {
    if (!stopping) {
      console.error(`${name} exited (${code})`);
      stop(code ?? 1);
    }
  });
}
start(
  'API',
  'uv',
  [
    'run',
    'uvicorn',
    'app.main:create_app',
    '--factory',
    '--host',
    '127.0.0.1',
    '--port',
    String(apiPort),
  ],
  backend,
);
start('Worker', 'uv', ['run', 'python', '-m', 'app.workers.local'], backend);
start('Agent', 'uv', ['run', 'python', '-m', 'app.workers.agent'], backend);
start(
  'Web',
  'pnpm',
  ['exec', 'vite', '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'],
  resolve(root, 'apps/web'),
);
start(
  'Admin',
  'pnpm',
  ['exec', 'vite', '--host', '127.0.0.1', '--port', String(adminPort), '--strictPort'],
  resolve(root, 'apps/admin'),
);
console.log(
  `\n映序启动中：用户端 http://127.0.0.1:${webPort} · 管理端 http://127.0.0.1:${adminPort} · API http://127.0.0.1:${apiPort}/docs\n`,
);

start('Knowledge', 'uv', ['run', 'python', '-m', 'app.workers.knowledge'], backend);

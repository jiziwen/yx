/** 跨前端业务验收；使用隔离数据库，端口与临时数据库均隔离，不影响正在使用的工作室。 */
import { defineConfig, devices } from '@playwright/test';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { resolve } from 'node:path';
mkdirSync('.data/e2e', { recursive: true });
const runDirectory = mkdtempSync(resolve('.data/e2e/run-'));
export default defineConfig({
  metadata: { databasePath: resolve(runDirectory, 'database.db') },
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: 'http://127.0.0.1:5373',
    trace: 'retain-on-failure',
    contextOptions: { reducedMotion: 'reduce' },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'node scripts/dev.mjs',
    url: 'http://127.0.0.1:8200/ready',
    timeout: 120000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5000 },
    env: {
      DATABASE_URL: 'sqlite:///' + resolve(runDirectory, 'database.db'),
      STORAGE_ROOT: resolve(runDirectory, 'objects'),
      APP_ENV: 'test',
      KNOWLEDGE_DEVELOPMENT_EMBEDDING: 'true',
      YINGXU_WEB_PORT: '5373',
      YINGXU_ADMIN_PORT: '5374',
      YINGXU_API_PORT: '8200',
    },
  },
});

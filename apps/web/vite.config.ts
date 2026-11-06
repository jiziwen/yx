/** web 独立开发/构建入口；开发代理避免浏览器暴露上游凭证。 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5273,
    proxy: { '/api': `http://127.0.0.1:${process.env.YINGXU_API_PORT ?? 8100}` },
  },
});

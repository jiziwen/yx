/** 独立管理前端入口；不依赖用户端状态、主题或身份。 */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './app/App';
import './styles.css';
const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 10000 }, mutations: { retry: false } },
});
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);

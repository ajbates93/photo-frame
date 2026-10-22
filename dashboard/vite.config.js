import { defineConfig } from 'vite';
import { mockApi } from './dev/mock-api.js';

// VITE_API=server: talk to the real home hub instead of the mock plugin.
const useServer = process.env.VITE_API === 'server';

export default defineConfig({
  plugins: useServer ? [] : [mockApi()], // serve mode only (apply: 'serve')
  build: {
    target: 'chrome106',
    cssTarget: 'chrome61',
  },
  server: {
    host: true,
    ...(useServer ? { proxy: { '/api': 'http://localhost:8000' } } : {}),
  },
});

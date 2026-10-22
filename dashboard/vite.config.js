import { defineConfig } from 'vite';
import { mockApi } from './dev/mock-api.js';

export default defineConfig({
  plugins: [mockApi()], // serve mode only (apply: 'serve')
  build: {
    target: 'chrome106',
    cssTarget: 'chrome61',
  },
  server: {
    host: true,
  },
});

import { defineConfig } from 'vite';

export default defineConfig({
  // Mock-API plugin slot (added in a later task): plugins: [mockApi()]
  plugins: [],
  build: {
    target: 'chrome106',
    cssTarget: 'chrome61',
  },
  server: {
    host: true,
  },
});

import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  server: { port: 4321 },
  vite: {
    build: { chunkSizeWarningLimit: 1200 },
  },
});

import { defineConfig } from 'astro/config';

// `site` dipakai untuk canonical + og:url/og:image. Harus absolut supaya scraper
// (WhatsApp, LinkedIn, Discord) bisa mengambil kartu share-nya.
// Kalau domain deploy berubah, ubah di sini lalu build ulang.
export default defineConfig({
  site: 'https://pantau-dbd.vercel.app',
  output: 'static',
  server: { port: 4321 },
  vite: {
    build: { chunkSizeWarningLimit: 1200 },
  },
});

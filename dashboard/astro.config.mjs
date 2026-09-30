import { defineConfig } from 'astro/config';

// `site` dipakai untuk canonical + og:url/og:image. Harus absolut supaya scraper
// (WhatsApp, LinkedIn, Discord) bisa mengambil kartu share-nya.
//
// PENTING: nilai ini harus sama persis dengan domain yang benar-benar melayani
// halaman. `pantau-dbd.vercel.app` sudah dipakai orang lain, jadi alias project ini
// adalah `pantau-dbd-seven.vercel.app`. Kalau URL-nya salah, og:image menunjuk berkas
// yang tidak ada dan kartu share-nya kosong tanpa error apa pun.
// Kalau domain deploy berubah, ubah di sini lalu build ulang.
export default defineConfig({
  site: 'https://pantau-dbd-seven.vercel.app',
  output: 'static',
  server: { port: 4321 },
  vite: {
    build: { chunkSizeWarningLimit: 1200 },
  },
});

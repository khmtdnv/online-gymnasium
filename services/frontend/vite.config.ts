import { reactRouter } from '@react-router/dev/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), reactRouter()],
  // Prerender обращается к preview по loopback: localhost в Docker может
  // слушать только IPv6, тогда как HTTP-клиент выбирает IPv4.
  preview: { host: '127.0.0.1' },
  server: {
    port: 5173,
    strictPort: true,
    hmr: { clientPort: 8080 },
  },
});

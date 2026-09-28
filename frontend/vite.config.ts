import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    open: true,
    proxy: {
      '/api': 'http://127.0.0.1:47831',
    },
  },
  build: {
    outDir: '../web',
    emptyOutDir: true,
  },
});

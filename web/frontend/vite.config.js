import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: proxy /api 到 FastAPI (8501)；build 产物到 dist/，由后端托管
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8501',
      '/static': 'http://127.0.0.1:8501',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
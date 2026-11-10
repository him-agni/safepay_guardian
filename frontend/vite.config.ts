import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The browser only ever talks to /api on this dev server; Vite forwards it to the FastAPI backend,
// so there is no CORS setup and the backend stays the only thing that talks to PayPal and the AI.
const backend = process.env.SAFEPAY_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    // AG Grid (~1 MB) and AG Charts (~1.1 MB) are split into their own chunks and only loaded on the
    // guardian's Activity and Insights tabs, so the sender never downloads them.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})

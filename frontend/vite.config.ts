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
    // AG Grid is ~880 kB minified; it is split into its own chunk and only loaded on the guardian's
    // Activity tab, so the sender never downloads it.
    chunkSizeWarningLimit: 1000,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// In development the app calls /api, exactly as it does behind nginx; Vite
// forwards those calls to the local backend so no CORS or env setup is needed.
const backend = process.env.VITE_DEV_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: backend, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') } },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', restoreMocks: true },
})

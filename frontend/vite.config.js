import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // In dev: proxy all /api, /health, /pay, /payment to FastAPI backend
      // This avoids CORS issues in development.
      proxy: {
        '/api':     { target: backendTarget, changeOrigin: true },
        '/health':  { target: backendTarget, changeOrigin: true },
        '/pay':     { target: backendTarget, changeOrigin: true },
        '/payment': { target: backendTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
  }
})

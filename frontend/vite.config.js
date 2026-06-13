import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式下 /api 代理到 FastAPI 后端。
// 后端不在 8000 端口时：BACKEND=http://127.0.0.1:8001 npm run dev
const backend = process.env.BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
    },
  },
})

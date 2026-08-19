import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 3000,
    // 监听全部网卡，外网可访问；只听 127.0.0.1 时远端连不上。
    host: '0.0.0.0',
    // /v1 同源代理到本机 gr-api（端口取根 .env 的 WEB_PORT）。
    // 走代理后前端与接口同源，不触发 CORS，8001 也不必对外暴露。
    proxy: { '/v1': 'http://127.0.0.1:8001' },
  },
  resolve: {
    alias: {
      // 用 import.meta.dirname 而非 __dirname：Vite 8 的 native config loader
      // （未来大版本的默认值）不支持 CJS 的 __dirname。
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
})

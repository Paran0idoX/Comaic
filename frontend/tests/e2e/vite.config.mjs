import { defineConfig } from '../../node_modules/vite/dist/node/index.js'
import { fileURLToPath } from 'node:url'

// 预览已构建的真实页面，仅代理到隔离 E2E API，避免碰到开发者正在运行的后端。
export default defineConfig({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  build: { outDir: fileURLToPath(new URL('../../../.codex-artifacts/simplicity-frontend-build', import.meta.url)) },
  preview: { host: '127.0.0.1', port: 15274, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:18124', changeOrigin: true } } },
})

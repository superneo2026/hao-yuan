import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8130,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8030', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8030', ws: true }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})

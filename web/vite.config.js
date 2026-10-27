import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const here = fileURLToPath(new URL('.', import.meta.url))
const runtimeFile = path.resolve(here, '../api/data/runtime.json')

function readRuntime() {
  try {
    return JSON.parse(fs.readFileSync(runtimeFile, 'utf-8'))
  } catch {
    return {}
  }
}

function updateRuntime(patch) {
  try {
    const data = { ...readRuntime(), ...patch }
    fs.mkdirSync(path.dirname(runtimeFile), { recursive: true })
    fs.writeFileSync(runtimeFile, JSON.stringify(data, null, 2))
  } catch {
    /* runtime file is best-effort */
  }
}

const env = process.env
const apiPort = Number(env.HAOYUAN_API_PORT || readRuntime().api_port) || 8030
const webPort = Number(env.HAOYUAN_WEB_PORT || readRuntime().web_port_config) || 8130
const apiTarget = `http://127.0.0.1:${apiPort}`

const runtimePortWriter = {
  name: 'haoyuan-runtime-port',
  configureServer(server) {
    if (!server.httpServer) return
    server.httpServer.once('listening', () => {
      const address = server.httpServer.address()
      if (address && typeof address === 'object' && address.port) {
        updateRuntime({ web_port: address.port })
      }
    })
  }
}

export default defineConfig({
  plugins: [vue(), runtimePortWriter],
  server: {
    port: webPort,
    strictPort: false,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/docs': { target: apiTarget, changeOrigin: true },
      '/ws': { target: `ws://127.0.0.1:${apiPort}`, ws: true }
    }
  },
  preview: {
    port: webPort,
    strictPort: false
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})

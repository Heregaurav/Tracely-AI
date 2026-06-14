import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ['three'],
    alias: {
      // some three internals import 'three/webgpu' which isn't exposed in all builds
      // alias it to a local shim that provides a no-op WebGPURenderer
      'three/webgpu': path.resolve(__dirname, 'src/three-webgpu-shim.js')
    }
  },
  server: {
    host: '127.0.0.1',
    port: 8000,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
      '/health': { target: 'http://localhost:5000', changeOrigin: true },
    }
  },
  build: { outDir: 'dist' }
})

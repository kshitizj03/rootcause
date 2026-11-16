import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// publicDir is the existing static site: results.html, incident.html, data/ and assets/
// are copied into dist/ untouched, so every URL stays relative.
export default defineConfig({
  base: './',
  publicDir: '../site',
  plugins: [react()],
  build: { assetsDir: '_app' },
  test: { environment: 'jsdom', setupFiles: ['src/test/setup.ts'] },
})

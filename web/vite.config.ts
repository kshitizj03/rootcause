import react from '@vitejs/plugin-react'
import { rmSync } from 'node:fs'
import { defineConfig } from 'vitest/config'

// publicDir is the existing static site: results.html, incident.html, data/ and assets/
// are copied into dist/ untouched, so every URL stays relative.
export default defineConfig({
  base: './',
  publicDir: '../site',
  plugins: [
    react(),
    // publicDir also carries site/tests (the old site's unit tests); they are not part of the published site.
    { name: 'drop-site-tests', closeBundle() { rmSync('dist/tests', { recursive: true, force: true }) } },
  ],
  build: { assetsDir: '_app' },
  test: { environment: 'jsdom', setupFiles: ['src/test/setup.ts'], include: ['src/**/*.test.{ts,tsx}'] },
})

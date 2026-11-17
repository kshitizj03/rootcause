// Post-build checks on dist/: JS budget, relative URLs only, old pages and data present, no test files published.
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const dist = fileURLToPath(new URL('../dist/', import.meta.url))
const walk = (d) => readdirSync(d).flatMap((f) => (statSync(join(d, f)).isDirectory() ? walk(join(d, f)) : [join(d, f)]))
const problems = []

const app = existsSync(join(dist, '_app')) ? walk(join(dist, '_app')) : []
const js = app.filter((f) => f.endsWith('.js'))
const gz = js.reduce((n, f) => n + gzipSync(readFileSync(f)).length, 0)
console.log(`gzipped JS: ${(gz / 1024).toFixed(1)} KB (budget 150 KB)`)
if (gz > 150 * 1024) problems.push('gzipped JS exceeds 150 KB')

for (const f of [join(dist, 'index.html'), ...app]) {
  if (!existsSync(f)) { problems.push(`missing ${f}`); continue }
  if (/src="\/|href="\/|url\(\//.test(readFileSync(f, 'utf8'))) problems.push(`absolute URL in ${f}`)
}
for (const f of ['results.html', 'incident.html', 'card.html', 'data/index.json']) {
  if (!existsSync(join(dist, f))) problems.push(`missing dist/${f}`)
}
if (existsSync(join(dist, 'tests'))) problems.push('dist/tests must not be published')

if (problems.length) { console.error(problems.join('\n')); process.exit(1) }
console.log('dist ok')

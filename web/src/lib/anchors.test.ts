import { it, expect } from 'vitest'
import { oldAnchorRedirect } from './anchors'

it('sends the old landing anchors to results.html', () => {
  for (const h of ['#every-run', '#findings', '#by-type', '#reproduce', '#result']) expect(oldAnchorRedirect(h)).toBe(`results.html${h}`)
})

it('leaves the new anchors and empty hashes alone', () => {
  for (const h of ['#results', '#runs', '#method', '#story', '']) expect(oldAnchorRedirect(h)).toBeNull()
})

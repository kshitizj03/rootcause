import { render } from '@testing-library/react'
import { it, expect } from 'vitest'
import { RichText } from './RichText'

it('turns the allowed tags into elements', () => {
  const { container } = render(
    <p>
      <RichText html={'a <span class="ok">Right.</span> b <span class="bad">Wrong.</span> <strong>c</strong>'} />
    </p>,
  )
  expect(container.querySelector('span.ok')).toHaveTextContent('Right.')
  expect(container.querySelector('span.bad')).toHaveTextContent('Wrong.')
  expect(container.querySelector('strong')).toHaveTextContent('c')
})

it('leaves anything else as literal text', () => {
  const evil = '<img src=x onerror=alert(1)> <script>alert(1)</script> <span class="x" onclick="y">z</span>'
  const { container } = render(<p><RichText html={evil} /></p>)
  expect(container.querySelector('img, script, span')).toBeNull()
  expect(container.textContent).toBe(evil)
})

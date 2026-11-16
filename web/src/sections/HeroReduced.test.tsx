import { render } from '@testing-library/react'
import { it, expect, beforeAll } from 'vitest'
import { Hero } from './Hero'

// Motion reads the preference once, so this lives in its own file with the stub in place first.
beforeAll(() => {
  const real = window.matchMedia
  window.matchMedia = ((q: string) => ({ ...real(q), matches: q.includes('prefers-reduced-motion') })) as typeof window.matchMedia
})

it('renders words in their final state under reduced motion', () => {
  const { container } = render(<Hero data={null} />)
  const words = container.querySelectorAll<HTMLElement>('.w')
  expect(words.length).toBe(4)
  words.forEach((w) => expect(w.style.opacity).not.toBe('0'))
})

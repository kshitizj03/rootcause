import { render } from '@testing-library/react'
import { it, expect } from 'vitest'
import { PHONE_LABELS } from './layout'
import { ServiceMap } from './ServiceMap'

it('renders 16 services and 16 calls', () => {
  const { container } = render(<ServiceMap variant="story" />)
  expect(container.querySelectorAll('.node')).toHaveLength(16)
  expect(container.querySelectorAll('.edge')).toHaveLength(16)
})

it("story variant reports the step and the run's verdict", () => {
  const { container } = render(<ServiceMap variant="story" step={5} agentOk={false} />)
  const svg = container.querySelector('svg')!
  expect(svg).toHaveAttribute('data-step', '5')
  expect(svg).toHaveAttribute('data-ok', '0')
})

it('hero variant has no labels and is hidden from screen readers', () => {
  const { container } = render(<ServiceMap variant="hero" />)
  const svg = container.querySelector('svg')!
  expect(svg).toHaveAttribute('aria-hidden', 'true')
  expect(container.querySelectorAll('text')).toHaveLength(0)
})

it('story variant describes the step in its aria-label', () => {
  const { container } = render(<ServiceMap variant="story" step={3} />)
  const svg = container.querySelector('svg')!
  expect(svg).toHaveAttribute('role', 'img')
  expect(svg.getAttribute('aria-label')).toContain('the rule names cart')
})

it('crops the viewBox and labels only five services on a phone', () => {
  const real = window.matchMedia
  window.matchMedia = ((q: string) => ({ ...real(q), matches: q.includes('max-width: 860px') })) as typeof window.matchMedia
  let container: HTMLElement
  try {
    container = render(<ServiceMap variant="story" />).container
  } finally {
    window.matchMedia = real
  }
  expect(container.querySelector('svg')).toHaveAttribute('viewBox', '20 150 520 220')
  const labels = [...container.querySelectorAll('.node text')].map((t) => t.textContent)
  expect(labels.sort()).toEqual([...PHONE_LABELS].sort())
})

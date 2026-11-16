import { render } from '@testing-library/react'
import { it, expect } from 'vitest'
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

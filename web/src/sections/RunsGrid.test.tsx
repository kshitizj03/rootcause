import { act, render, screen, waitFor } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import { useReducedMotion } from 'motion/react'
import { RunsGrid } from './RunsGrid'
import { GRID_SOLVERS, availableSolvers } from './gridSolvers'
import { MockIntersectionObserver } from '../test/setup'
import { fixtureWithGridSolvers, ULTRA } from '../test/fixture'
import { investigationCount, overallOf, faultIncidents } from '../lib/results'

vi.mock('motion/react', async (orig) => ({ ...(await orig<typeof import('motion/react')>()), useReducedMotion: vi.fn(() => true) }))
afterEach(() => vi.mocked(useReducedMotion).mockReturnValue(true))

it('heading shows the investigation count', () => {
  const d = fixtureWithGridSolvers()
  render(<RunsGrid data={d} />)
  const n = investigationCount(d, overallOf(d)).toLocaleString('en-US')
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(`${n} investigations.None hidden.`)
})

it('never reads zero: the total is there before the heading is in view, and the count ends at it', async () => {
  vi.mocked(useReducedMotion).mockReturnValue(false)
  const d = fixtureWithGridSolvers()
  const n = investigationCount(d, overallOf(d)).toLocaleString('en-US')
  const { container } = render(<RunsGrid data={d} />)
  expect(screen.getByRole('heading', { level: 2, name: `${n} investigations. None hidden.` })).toBeInTheDocument()
  expect(container.querySelector('.count')).toHaveTextContent(n)
  expect(container.querySelector('.grid')).not.toHaveClass('in')
  act(() => MockIntersectionObserver.instances.forEach((o) => o.trigger(true)))
  await waitFor(() => expect(container.querySelector('.count')).toHaveTextContent(n))
  expect(container.querySelector('.grid')).toHaveClass('in')
})

it('under reduced motion the count is final and the tiles are shown', () => {
  const { container } = render(<RunsGrid data={fixtureWithGridSolvers()} />)
  expect(container.querySelector('.grid')).toHaveClass('in')
})

it('one link per recorded run, with the replay URL', () => {
  const d = fixtureWithGridSolvers()
  const { container } = render(<RunsGrid data={d} />)
  const tiles = [...container.querySelectorAll<HTMLAnchorElement>('a.t')]
  const want = faultIncidents(d).reduce((t, i) => t + availableSolvers(d, overallOf(d), GRID_SOLVERS).reduce((u, s) => u + i.results[s].length, 0), 0)
  expect(tiles).toHaveLength(want)
  expect(tiles[0].getAttribute('href')).toBe('incident.html?id=ad-failure&solver=heuristic&run=1')
  expect(tiles[1].getAttribute('href')).toBe('incident.html?id=ad-failure&solver=claude-code-opus-5.5&run=1')
  expect(tiles[0]).toHaveAccessibleName('ad-failure, Heuristic, run 1: correct')
  expect(tiles[0]).toHaveAttribute('title', 'ad-failure, Heuristic, run 1: correct')
  const half = screen.getByRole('link', { name: 'ad-failure, V1 on Nemotron 3 Ultra, run 4: half right' })
  expect(half).toHaveClass('h')
  expect(screen.getByRole('link', { name: 'cart-silent, Heuristic, run 1: wrong' })).toHaveClass('x')
})

it('a partial or missing solver gets no column', () => {
  const d = fixtureWithGridSolvers()
  d.incidents[0].results[ULTRA] = [1]
  const { container } = render(<RunsGrid data={d} />)
  expect(container).not.toHaveTextContent('Nemotron 3 Ultra')
  expect(availableSolvers(d, overallOf(d), GRID_SOLVERS)).not.toContain(ULTRA)
})

it('links to the full scoreboard', () => {
  render(<RunsGrid data={fixtureWithGridSolvers()} />)
  expect(screen.getByRole('link', { name: /Open the full scoreboard/ })).toHaveAttribute('href', 'results.html#every-run')
})

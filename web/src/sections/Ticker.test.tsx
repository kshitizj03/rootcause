import { render, screen, fireEvent } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import { useReducedMotion } from 'motion/react'
import { Ticker } from './Ticker'
import { fixtureWithGridSolvers, GLM, ULTRA } from '../test/fixture'

vi.mock('motion/react', async (orig) => ({ ...(await orig<typeof import('motion/react')>()), useReducedMotion: vi.fn(() => false) }))
afterEach(() => vi.mocked(useReducedMotion).mockReturnValue(false))

const items = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>('.item')]

it('one item per fault incident', () => {
  const { container } = render(<Ticker data={fixtureWithGridSolvers()} />)
  const visible = items(container).filter((i) => !i.closest('[aria-hidden]'))
  expect(visible).toHaveLength(2)
  expect(visible[0].textContent).toBe('ad-failure · rule ✓ · Opus 5/5 · Ultra 4/5 · GLM 4/5')
  expect(items(container)).toHaveLength(4)
})

it('says every agent missed when all scored 0', () => {
  const d = fixtureWithGridSolvers()
  for (const s of ['claude-code-opus-5.5', ULTRA, GLM]) d.incidents[1].results[s] = [0, 0, 0, 0, 0]
  const { container } = render(<Ticker data={d} />)
  expect(items(container)[1]).toHaveTextContent('cart-silent · rule ✗ · every agent 0 of 5')
})

it('leaves out a solver the release does not have', () => {
  const d = fixtureWithGridSolvers()
  d.solvers = d.solvers.filter((s) => s !== GLM)
  const { container } = render(<Ticker data={d} />)
  expect(container).not.toHaveTextContent('GLM')
  expect(container).toHaveTextContent('Ultra')
})

it('is static under reduced motion', () => {
  vi.mocked(useReducedMotion).mockReturnValue(true)
  render(<Ticker data={fixtureWithGridSolvers()} />)
  expect(screen.getByLabelText('Verdicts from recorded runs')).toHaveClass('static')
})

it('animates otherwise', () => {
  render(<Ticker data={fixtureWithGridSolvers()} />)
  expect(screen.getByLabelText('Verdicts from recorded runs')).not.toHaveClass('static')
})

it('a button pauses and resumes the marquee', () => {
  render(<Ticker data={fixtureWithGridSolvers()} />)
  const t = screen.getByLabelText('Verdicts from recorded runs')
  fireEvent.click(screen.getByRole('button', { name: 'Pause ticker' }))
  expect(t).toHaveClass('paused')
  fireEvent.click(screen.getByRole('button', { name: 'Resume ticker' }))
  expect(t).not.toHaveClass('paused')
  expect(screen.getByRole('button', { name: 'Pause ticker' })).toBeInTheDocument()
})

it('has no pause button under reduced motion', () => {
  vi.mocked(useReducedMotion).mockReturnValue(true)
  render(<Ticker data={fixtureWithGridSolvers()} />)
  expect(screen.queryByRole('button')).toBeNull()
})

it('omits the rule verdict when the release has no heuristic', () => {
  const d = fixtureWithGridSolvers()
  d.solvers = d.solvers.filter((s) => s !== 'heuristic')
  for (const i of d.incidents) delete i.results.heuristic
  const { container } = render(<Ticker data={d} />)
  expect(container).not.toHaveTextContent('rule')
  expect(container).toHaveTextContent('ad-failure · Opus 5/5')
})

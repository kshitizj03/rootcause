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
  expect(visible[0].textContent).toBe('ad-failure · rule ✓ · Opus 5/5 · Ultra 4.5/5 · GLM 4.5/5')
  expect(items(container)).toHaveLength(4)
})

it('says every agent missed when all scored 0', () => {
  const d = fixtureWithGridSolvers()
  for (const s of ['claude-code-opus-5.5', ULTRA, GLM]) d.incidents[1].results[s] = [0, 0, 0, 0, 0]
  const { container } = render(<Ticker data={d} />)
  expect(items(container)[1]).toHaveTextContent('cart-silent · rule ✗ · Opus, Ultra and GLM all 0 of 5')
})

it('does not say every agent when a solver that is not shown scored', () => {
  const d = fixtureWithGridSolvers()
  for (const s of ['claude-code-opus-5.5', ULTRA, GLM]) d.incidents[1].results[s] = [0, 0, 0, 0, 0]
  d.incidents[1].results['agent-v0-nemotron'] = [1, 1, 0, 0, 0]
  const { container } = render(<Ticker data={d} />)
  expect(items(container)[1]).not.toHaveTextContent('every agent')
  expect(items(container)[1]).toHaveTextContent('Opus, Ultra and GLM all 0 of 5')
})

it('shows half credit as a half, for the rule and for agents', () => {
  const d = fixtureWithGridSolvers()
  d.incidents[1].results.heuristic = [0.5]
  d.incidents[1].results[ULTRA] = [0.5, 1, 1, 0.5, 0.5]
  const { container } = render(<Ticker data={d} />)
  expect(items(container)[1]).toHaveTextContent('cart-silent · rule ½')
  expect(items(container)[1]).toHaveTextContent('Ultra 3.5/5')
})

it('takes the denominator from the recorded runs', () => {
  const d = fixtureWithGridSolvers()
  for (const i of d.incidents) i.results[GLM] = [1, 0, 1]
  d.planned_runs[GLM] = 3
  const { container } = render(<Ticker data={d} />)
  expect(items(container)[0]).toHaveTextContent('GLM 2/3')
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

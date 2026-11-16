import { render, screen, act, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { it, expect, vi, afterEach } from 'vitest'
import { useReducedMotion } from 'motion/react'
import { Story } from './Story'
import { STORY } from './valkey-cart'
import { MockIntersectionObserver } from '../test/setup'

vi.mock('motion/react', async (orig) => ({ ...(await orig<typeof import('motion/react')>()), useReducedMotion: vi.fn(() => false) }))

afterEach(() => vi.mocked(useReducedMotion).mockReturnValue(false))

const mapRoot = (c: HTMLElement) => c.querySelector('svg.map-story')!

/** Fires one observer entry, as if that step crossed the middle of the screen. */
function reach(n: number) {
  const obs = MockIntersectionObserver.instances.at(-1)!
  const target = [...obs.elements][n - 1]
  act(() => obs.callback([{ target, isIntersecting: true } as IntersectionObserverEntry], obs as unknown as IntersectionObserver))
}

it('starts on the right Nemotron run', () => {
  render(<Story story={STORY} />)
  expect(screen.getByRole('button', { name: /Nemotron · run 2 ✓/ })).toHaveAttribute('aria-pressed', 'true')
})

it('switching to run 3 shows the wrong verdict and its replay link', async () => {
  const { container } = render(<Story story={STORY} />)
  await userEvent.click(screen.getByRole('button', { name: /Nemotron · run 3/ }))
  const head = screen.getByRole('heading', { name: /^cart\. Wrong\.$/ })
  expect(head).toHaveTextContent('cart.')
  expect(screen.getByRole('link', { name: /Replay this run, step by step/ })).toHaveAttribute(
    'href',
    'incident.html?id=valkey-cart-paused&solver=agent-v1-nemotron&run=3',
  )
  expect(mapRoot(container)).toHaveAttribute('data-ok', '0')
})

it('the switcher works from the keyboard', async () => {
  render(<Story story={STORY} />)
  const user = userEvent.setup()
  const opus = screen.getByRole('button', { name: /Opus · run 1/ })
  for (let i = 0; i < 10 && document.activeElement !== opus; i++) await user.tab()
  expect(opus).toHaveFocus()
  await user.keyboard('{Enter}')
  expect(opus).toHaveAttribute('aria-pressed', 'true')
})

it('under reduced motion everything is in its final state', () => {
  vi.mocked(useReducedMotion).mockReturnValue(true)
  const { container } = render(<Story story={STORY} />)
  reach(4)
  const lines = container.querySelectorAll('.log .call')
  expect(lines).toHaveLength(STORY.runs[0].lines.length)
  lines.forEach((l) => expect(l).not.toHaveAttribute('aria-hidden', 'true'))
  container.querySelectorAll<HTMLElement>('.step').forEach((s) => expect(s.getAttribute('style')).toBeNull())
})

it('hides the log lines from screen readers until the alert', () => {
  const { container } = render(<Story story={STORY} />)
  container.querySelectorAll('.log .call').forEach((l) => expect(l).toHaveAttribute('aria-hidden', 'true'))
  expect(container.querySelector('.log')).not.toHaveAttribute('aria-live')
})

it('the active step drives the map', () => {
  const { container } = render(<Story story={STORY} />)
  reach(4)
  expect(mapRoot(container)).toHaveAttribute('data-step', '4')
  const log = container.querySelector('.log') as HTMLElement
  expect(log).toHaveAttribute('data-visible', 'true')
  expect(within(log).getByText(/service_map\(\)/)).toBeInTheDocument()
  expect(within(log).queryByText(/waiting for the alert/)).toBeNull()
})

it('the log waits for the alert before step 4', () => {
  render(<Story story={STORY} />)
  reach(2)
  expect(screen.getByText('waiting for the alert…')).toBeInTheDocument()
})

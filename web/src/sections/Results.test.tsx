import { render, screen } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import { useReducedMotion } from 'motion/react'
import { Results } from './Results'
import { fixtureIndex } from '../test/fixture'
import { at, forestDomain, vsRuleRows, mainSolvers, overallOf } from '../lib/results'

vi.mock('motion/react', async (orig) => ({ ...(await orig<typeof import('motion/react')>()), useReducedMotion: vi.fn(() => false) }))

afterEach(() => vi.mocked(useReducedMotion).mockReturnValue(false))

const rows = (c: HTMLElement) => [...c.querySelectorAll<HTMLElement>('.frow')]

it('heading comes from heroAnswer', () => {
  render(<Results data={fixtureIndex()} />)
  expect(screen.getByRole('heading', { name: 'Only the strongest models.' })).toBeInTheDocument()
})

it('rows are ordered by mean and labelled by strength', () => {
  const { container } = render(<Results data={fixtureIndex()} />)
  expect(rows(container).map((r) => r.dataset.strength)).toEqual(['clear', 'none'])
  expect(rows(container)[0]).toHaveTextContent('Claude Opus 5.5')
  expect(rows(container)[0]).toHaveTextContent('+0.90')
})

it('a suggestive row carries the tag', () => {
  const d = fixtureIndex()
  const p = d.paired.find((x) => x.a === 'agent-v1-nemotron')!
  p.ci = [0.1, 0.7]
  p.p = 0.09
  const { container } = render(<Results data={d} />)
  const r = rows(container)[1]
  expect(r.dataset.strength).toBe('suggestive')
  expect(r).toHaveTextContent('suggestive')
  expect(rows(container)[0]).not.toHaveTextContent('suggestive')
})

it('wins and losses are optional', () => {
  const d = fixtureIndex()
  const p = d.paired.find((x) => x.a === 'agent-v1-nemotron')!
  delete p.wins
  delete p.losses
  const { container } = render(<Results data={d} />)
  expect(rows(container)[0]).toHaveTextContent('won 2, lost 0')
  expect(rows(container)[1]).toHaveTextContent('55% right')
  expect(rows(container)[1]).not.toHaveTextContent('won')
})

it('under reduced motion bars render at their final width', () => {
  vi.mocked(useReducedMotion).mockReturnValue(true)
  const d = fixtureIndex()
  const { container } = render(<Results data={d} />)
  const list = vsRuleRows(d, mainSolvers(d, overallOf(d)))
  const dom = forestDomain(list)
  const bar = rows(container)[0].querySelector<HTMLElement>('.bar')!
  expect(bar.style.left).toBe(at(list[0].ci[0], dom))
  expect(bar.style.width).toBe(`${(parseFloat(at(list[0].ci[1], dom)) - parseFloat(at(list[0].ci[0], dom))).toFixed(2)}%`)
})

import { render, screen } from '@testing-library/react'
import { it, expect } from 'vitest'
import { Hero } from './Hero'
import { fixtureIndex } from '../test/fixture'

it('shows the incident count from the data', () => {
  const { container } = render(<Hero data={fixtureIndex()} />)
  expect(container.querySelector('.pill')).toHaveTextContent('3 recorded incidents')
})

it('splits outages from controls in the subhead', () => {
  const { container } = render(<Hero data={fixtureIndex()} />)
  expect(container.querySelector('.sub')).toHaveTextContent('on 3 incidents (2 outages and 1 no-fault controls)')
})

it('uses the static counts before data arrives', () => {
  const { container } = render(<Hero data={null} />)
  expect(container.querySelector('.sub')).toHaveTextContent('on 20 incidents (16 outages and 4 no-fault controls)')
})

it('shows the question before data arrives', () => {
  render(<Hero data={null} />)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Which service?')
})

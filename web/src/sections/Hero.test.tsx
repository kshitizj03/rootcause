import { render, screen } from '@testing-library/react'
import { it, expect } from 'vitest'
import { Hero } from './Hero'
import { fixtureIndex } from '../test/fixture'

it('shows the incident count from the data', () => {
  const { container } = render(<Hero data={fixtureIndex()} />)
  expect(container.querySelector('.pill')).toHaveTextContent('3 recorded outages')
})

it('shows the question before data arrives', () => {
  render(<Hero data={null} />)
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Which service?')
})

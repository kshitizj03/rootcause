import { render, screen } from '@testing-library/react'
import { it, expect } from 'vitest'
import App from './App'

it('renders the hero question', () => {
  render(<App />)
  const h1 = screen.getByRole('heading', { level: 1 })
  expect(h1).toHaveTextContent('Something broke.')
  expect(h1).toHaveTextContent('Which service?')
})

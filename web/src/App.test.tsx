import { render, screen } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import App from './App'
import { fixtureIndex } from './test/fixture'

afterEach(() => vi.unstubAllGlobals())

it('renders the hero question', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => fixtureIndex() })))
  render(<App />)
  const h1 = screen.getByRole('heading', { level: 1 })
  expect(h1).toHaveTextContent('Something broke.')
  expect(h1).toHaveTextContent('Which service?')
  expect(await screen.findByText(/data-v4 · 3 recorded incidents/)).toBeInTheDocument()
})

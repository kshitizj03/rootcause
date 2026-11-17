import { render, screen } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import App from './App'

afterEach(() => vi.unstubAllGlobals())

it('a failed load keeps the hero and says the results could not be loaded', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))
  const { container } = render(<App />)
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
  expect(container.querySelector('#results')).toBeNull()
  expect(container.querySelector('.ticker')).toBeNull()
  expect(container.querySelector('.grid')).toBeNull()
})

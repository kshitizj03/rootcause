import { render, screen } from '@testing-library/react'
import { it, expect, vi, afterEach } from 'vitest'
import App from './App'
import { fixtureIndex } from './test/fixture'

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

it('a section that throws renders the alert and keeps the h1', async () => {
  const d = fixtureIndex()
  d.summary = {} as typeof d.summary
  d.paired = null as unknown as typeof d.paired
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => d })))
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument()
})

it('has a skip link to the story', () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))
  render(<App />)
  expect(screen.getByRole('link', { name: 'Skip to the investigation' })).toHaveAttribute('href', '#story')
})

it('scrolls a deep link into view once the data has loaded, and when the load fails', async () => {
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  location.hash = '#results'
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => fixtureIndex() })))
  const { container, unmount } = render(<App />)
  await screen.findByText(/data-v4/)
  await vi.waitFor(() => expect(scroll.mock.contexts).toContain(container.querySelector('#results')))
  unmount()
  scroll.mockClear()
  location.hash = '#method'
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })))
  const again = render(<App />)
  await screen.findByRole('alert')
  await vi.waitFor(() => expect(scroll.mock.contexts).toContain(again.container.querySelector('#method')))
  location.hash = ''
})

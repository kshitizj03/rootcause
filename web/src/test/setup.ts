import '@testing-library/jest-dom/vitest'

window.matchMedia = (query: string) =>
  ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList

// Records every instance so tests can fire entries by hand.
export class MockIntersectionObserver {
  static instances: MockIntersectionObserver[] = []
  readonly elements = new Set<Element>()
  callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    MockIntersectionObserver.instances.push(this)
  }
  observe(el: Element) { this.elements.add(el) }
  unobserve(el: Element) { this.elements.delete(el) }
  disconnect() { this.elements.clear() }
  takeRecords(): IntersectionObserverEntry[] { return [] }
  trigger(isIntersecting: boolean) {
    const entries = [...this.elements].map(
      (target) => ({ target, isIntersecting, intersectionRatio: isIntersecting ? 1 : 0 }) as IntersectionObserverEntry,
    )
    this.callback(entries, this as unknown as IntersectionObserver)
  }
}
window.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver

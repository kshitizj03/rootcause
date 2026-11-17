import { Component, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { IndexData } from './data/types'
import { loadIndex } from './data/load'
import { Nav } from './sections/Nav'
import { Hero } from './sections/Hero'
import { Story } from './story/Story'
import { STORY } from './story/valkey-cart'
import { Results } from './sections/Results'
import { Ticker } from './sections/Ticker'
import { RunsGrid } from './sections/RunsGrid'
import { Method } from './sections/Method'
import { Footer } from './sections/Footer'

const LoadError = () => (
  <p role="alert" className="wrap load-error">The results could not be loaded. Try reloading the page.</p>
)

// A schema drift that throws in a data section must not blank the hero.
class DataBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <LoadError /> : this.props.children }
}

export default function App() {
  const [data, setData] = useState<IndexData | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    loadIndex().then((d) => live && setData(d), () => live && setFailed(true))
    return () => { live = false }
  }, [])
  // The browser's fragment scroll ran before these sections mounted, so repeat it once they have.
  useEffect(() => {
    if (data || failed) document.getElementById(location.hash.slice(1))?.scrollIntoView()
  }, [data, failed])
  return (
    <>
      <a className="skip" href="#story">Skip to the investigation</a>
      <Nav />
      <main>
        <Hero data={data} />
        {failed && <LoadError />}
        <Story story={STORY} />
        {data && (
          <DataBoundary>
            <Results data={data} />
            <Ticker data={data} />
            <RunsGrid data={data} />
          </DataBoundary>
        )}
        <Method />
      </main>
      <Footer />
    </>
  )
}

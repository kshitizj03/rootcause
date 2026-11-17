import { useEffect, useState } from 'react'
import type { IndexData } from './data/types'
import { loadIndex } from './data/load'
import { Nav } from './sections/Nav'
import { Hero } from './sections/Hero'
import { Story } from './story/Story'
import { STORY } from './story/valkey-cart'
import { Results } from './sections/Results'
import { Ticker } from './sections/Ticker'
import { RunsGrid } from './sections/RunsGrid'
import { Footer } from './sections/Footer'

export default function App() {
  const [data, setData] = useState<IndexData | null>(null)
  useEffect(() => {
    let live = true
    // Task 9 adds the error state; until then a failed load leaves the hero as is.
    loadIndex().then((d) => live && setData(d), () => {})
    return () => { live = false }
  }, [])
  return (
    <>
      <Nav />
      <main>
        <Hero data={data} />
        <Story story={STORY} />
        {data && <Results data={data} />}
        {data && <Ticker data={data} />}
        {data && <RunsGrid data={data} />}
      </main>
      <Footer />
    </>
  )
}

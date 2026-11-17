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
import { Method } from './sections/Method'
import { Footer } from './sections/Footer'

export default function App() {
  const [data, setData] = useState<IndexData | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true
    loadIndex().then((d) => live && setData(d), () => live && setFailed(true))
    return () => { live = false }
  }, [])
  return (
    <>
      <Nav />
      <main>
        <Hero data={data} />
        {failed && (
          <p role="alert" className="wrap load-error">The results could not be loaded. Try reloading the page.</p>
        )}
        <Story story={STORY} />
        {data && <Results data={data} />}
        {data && <Ticker data={data} />}
        {data && <RunsGrid data={data} />}
        <Method />
      </main>
      <Footer />
    </>
  )
}

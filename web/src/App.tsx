import { useEffect, useState } from 'react'
import type { IndexData } from './data/types'
import { loadIndex } from './data/load'
import { Nav } from './sections/Nav'
import { Hero } from './sections/Hero'
import { Story } from './story/Story'
import { STORY } from './story/valkey-cart'
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
      </main>
      <Footer />
    </>
  )
}

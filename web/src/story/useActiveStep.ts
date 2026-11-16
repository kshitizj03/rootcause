import { useCallback, useEffect, useRef, useState } from 'react'

/** The step crossing the middle of the screen (the lower band on phones, above the pinned stage). 1-based, 0 before the first. */
export function useActiveStep(count: number) {
  const [active, setActive] = useState(0)
  const els = useRef<(HTMLElement | null)[]>([])
  const refs = useCallback((el: HTMLElement | null, i: number) => { els.current[i] = el }, [])

  useEffect(() => {
    const phone = window.matchMedia('(max-width: 860px)').matches
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const i = els.current.indexOf(e.target as HTMLElement)
          if (e.isIntersecting && i >= 0) setActive(i + 1)
        }
      },
      { rootMargin: phone ? '-78% 0px -12% 0px' : '-45% 0px -45% 0px' },
    )
    els.current.slice(0, count).forEach((el) => el && io.observe(el))
    return () => io.disconnect()
  }, [count])

  return { active, refs }
}

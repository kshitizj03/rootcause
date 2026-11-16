import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { IndexData } from '../data/types'
import { ServiceMap } from '../map/ServiceMap'

const ease = [0.2, 0.7, 0.2, 1] as const

// Under reduced motion these render their final state with no `initial`, so no inline opacity: 0.
function Word({ delay, children }: { delay: number; children: ReactNode }) {
  const reduce = useReducedMotion()
  if (reduce) return <span className="w">{children}</span>
  return (
    <motion.span
      className="w"
      initial={{ opacity: 0, y: '0.35em', filter: 'blur(6px)' }}
      animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
      transition={{ duration: 1, delay, ease }}
    >
      {children}
    </motion.span>
  )
}

function Fade({ tag, className, delay, children }: { tag: 'p' | 'div'; className: string; delay: number; children: ReactNode }) {
  const reduce = useReducedMotion()
  if (reduce) return tag === 'p' ? <p className={className}>{children}</p> : <div className={className}>{children}</div>
  const M = motion[tag]
  return (
    <M className={className} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1, delay }}>
      {children}
    </M>
  )
}

export function Hero({ data }: { data: IndexData | null }) {
  const n = data ? data.incidents.length : 20
  return (
    <section className="hero">
      <div className="hero-map" aria-hidden="true">
        <ServiceMap variant="hero" />
      </div>
      <div className="hero-copy wrap">
        <a className="pill" href="#runs">
          <b />
          <span>
            data-v4 · {n} recorded outages<span className="pill-more"> · every run public</span>
          </span>
        </a>
        <h1>
          <Word delay={0.1}>Something</Word> <Word delay={0.2}>broke.</Word>
          <br />
          <em>
            <Word delay={0.45}>Which</Word> <Word delay={0.55}>service?</Word>
          </em>
        </h1>
        <Fade tag="p" className="sub" delay={0.9}>
          LLM agents get the tools an SRE uses (metrics, traces and logs) on 20 outages recorded from a 28-service shop. A
          28-line rule gets the same data. Both are scored against the truth.
        </Fade>
        <Fade tag="div" className="ctas" delay={1.1}>
          <a className="btn solid" href="#story">Watch an investigation</a>
          <a className="btn" href="#results">See the results</a>
        </Fade>
      </div>
      <div className="scroll-hint">scroll</div>
    </section>
  )
}

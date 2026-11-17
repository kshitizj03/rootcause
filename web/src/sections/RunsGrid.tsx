import { Fragment, useEffect, useRef, useState } from 'react'
import { animate, useInView, useReducedMotion } from 'motion/react'
import type { IndexData } from '../data/types'
import { faultIncidents, investigationCount, mark, overallOf, solverName } from '../lib/results'
import { GRID_SOLVERS, availableSolvers } from './gridSolvers'

const HEAD: Record<string, string> = {
  heuristic: 'Rule',
  'claude-code-opus-5.5': 'Claude Opus 5.5',
  'agent-v1@nvidia-nemotron-3-ultra-550b-a55b': 'Nemotron 3 Ultra',
  'agent-v1@z-ai-glm-5.3-flash': 'GLM 5.3 Flash',
}

const fmt = (n: number) => n.toLocaleString('en-US')

export function RunsGrid({ data }: { data: IndexData }) {
  const reduced = useReducedMotion()
  const overall = overallOf(data)
  const total = investigationCount(data, overall)
  const cols = availableSolvers(data, overall, GRID_SOLVERS)
  const gridRef = useRef<HTMLDivElement>(null)
  const headRef = useRef<HTMLHeadingElement>(null)
  const inView = useInView(gridRef, { once: true, margin: '-10% 0px' })
  const headInView = useInView(headRef, { once: true, amount: 0.6 })
  // Starts at the real total so no reader ever sees a stuck 0; the count-up replays from 0 once the heading is on screen.
  const [shown, setShown] = useState(total)
  useEffect(() => {
    if (reduced || !headInView) return
    const c = animate(0, total, { duration: 1.6, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => setShown(Math.round(v)) })
    return () => c.stop()
  }, [reduced, headInView, total])
  const names = cols.map((s) => (s === 'heuristic' ? 'the rule' : HEAD[s]))
  const shownNames = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
  const cascade = reduced || inView
  const per = Math.max(1, ...faultIncidents(data).flatMap((i) => cols.map((s) => (i.results[s] ?? []).length)))
  return (
    <section className="runs wrap" id="runs">
      <span className="eyebrow">Every run, failures included</span>
      <h2 className="big" ref={headRef} aria-label={`${fmt(total)} investigations. None hidden.`}>
        <span className="count">{fmt(reduced ? total : shown)}</span> investigations.<br />None hidden.
      </h2>
      <p className="lede">
        Up to {per} runs per agent per incident, and each square opens its replay. Shown here: {shownNames}, on every fault
        incident.
      </p>
      <div className={`grid${cascade ? ' in' : ''}`} ref={gridRef} style={{ '--cols': cols.length } as React.CSSProperties}>
        <div className="hd">Incident</div>
        {cols.map((s) => <div className="hd" key={s}>{HEAD[s]}</div>)}
        {faultIncidents(data).map((i, ii) => (
          <Fragment key={i.id}>
            <div className="inc">{i.id}</div>
            {cols.map((s, ci) => (
              <div key={s}>
                <span className="tiles">
                  {(i.results[s] ?? []).map((c, n) => {
                    const m = mark(c)
                    const label = `${i.id}, ${solverName(s)}, run ${n + 1}: ${m.cls === 'part' ? 'half right' : m.word}`
                    return (
                      <a key={n} className={`t${m.cls === 'miss' ? ' x' : m.cls === 'part' ? ' h' : ''}`} style={{ '--i': (ii * cols.length + ci) * per + n } as React.CSSProperties}
                        href={`incident.html?id=${i.id}&solver=${encodeURIComponent(s)}&run=${n + 1}`} title={label}>
                        <span className="vh">{label}</span>
                      </a>
                    )
                  })}
                </span>
              </div>
            ))}
          </Fragment>
        ))}
      </div>
      <a className="more" href="results.html#every-run">Open the full scoreboard →</a>
    </section>
  )
}

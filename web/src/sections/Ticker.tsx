import { useReducedMotion } from 'motion/react'
import type { IndexData } from '../data/types'
import { availableSolvers, GRID_SOLVERS } from './RunsGrid'
import { faultIncidents, overallOf, rightOf } from '../lib/results'

const SHORT: Record<string, string> = {
  'claude-code-opus-5.5': 'Opus',
  'agent-v1@nvidia-nemotron-3-ultra-550b-a55b': 'Ultra',
  'agent-v1@z-ai-glm-5.3-flash': 'GLM',
}

export function Ticker({ data }: { data: IndexData }) {
  const reduced = useReducedMotion()
  const agents = availableSolvers(data, overallOf(data), GRID_SOLVERS.slice(1))
  const items = faultIncidents(data).map((i) => {
    const rule = (i.results.heuristic ?? [])[0] >= 1
    const counts = agents.map((s) => [SHORT[s], rightOf(i.results[s] ?? [])] as const)
    return (
      <span className="item" key={i.id}>
        <b>{i.id}</b> · rule <span className={rule ? 'ok' : 'bad'}>{rule ? '✓' : '✗'}</span>
        {counts.length > 0 && counts.every(([, n]) => n === 0)
          ? <> · <span className="bad">every agent 0 of 5</span></>
          : counts.map(([name, n]) => ` · ${name} ${n}/5`)}
      </span>
    )
  })
  return (
    <div role="region" className={`ticker${reduced ? ' static' : ''}`} aria-label="Verdicts from recorded runs">
      <div className="row">
        {items}
        {!reduced && <span className="dup" aria-hidden="true">{items}</span>}
      </div>
    </div>
  )
}

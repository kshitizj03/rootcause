import { useState } from 'react'
import { useReducedMotion } from 'motion/react'
import type { IndexData } from '../data/types'
import { availableSolvers, GRID_SOLVERS } from './gridSolvers'
import { faultIncidents, mark, overallOf, scoreOf } from '../lib/results'

const SHORT: Record<string, string> = {
  'claude-code-opus-5.5': 'Opus',
  'agent-v1@nvidia-nemotron-3-ultra-550b-a55b': 'Ultra',
  'agent-v1@z-ai-glm-5.3-flash': 'GLM',
}

export function Ticker({ data }: { data: IndexData }) {
  const reduced = useReducedMotion()
  const [paused, setPaused] = useState(false)
  const agents = availableSolvers(data, overallOf(data), GRID_SOLVERS.slice(1))
  const items = faultIncidents(data).map((i) => {
    const ruleRun = (i.results.heuristic ?? [])[0]
    const rm = ruleRun === undefined ? null : mark(ruleRun)
    const counts = agents.map((s) => {
      const runs = i.results[s] ?? []
      return { name: SHORT[s], score: scoreOf(runs), of: runs.length }
    })
    const none = counts.length > 0 && counts.every((c) => c.score === 0 && c.of > 0)
    const names = counts.map((c) => c.name)
    const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]
    return (
      <span className="item" key={i.id}>
        <b>{i.id}</b>
        {rm && <> · rule <span className={rm.cls === 'hit' ? 'ok' : rm.cls === 'miss' ? 'bad' : undefined}>{rm.glyph}</span></>}
        {none
          ? <> · <span className="bad">{list} {names.length > 1 ? 'all ' : ''}0 of {counts[0].of}</span></>
          : counts.map((c) => ` · ${c.name} ${c.score}/${c.of}`)}
      </span>
    )
  })
  return (
    <div role="region" className={`ticker${reduced ? ' static' : ''}${paused ? ' paused' : ''}`} aria-label="Verdicts from recorded runs">
      {!reduced && (
        <button type="button" className="pause" onClick={() => setPaused(!paused)}>
          {paused ? 'Resume ticker' : 'Pause ticker'}
        </button>
      )}
      <div className="view">
        <div className="row">
          {items}
          {!reduced && <span className="dup" aria-hidden="true">{items}</span>}
        </div>
      </div>
    </div>
  )
}

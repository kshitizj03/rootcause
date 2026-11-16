import type { CSSProperties } from 'react'
import { useReducedMotion } from 'motion/react'
import type { StoryRun } from './types'

export function ToolLog({ run, visible }: { run: StoryRun; visible: boolean }) {
  const reduce = useReducedMotion()
  return (
    <div className="log" aria-live="polite" data-visible={visible}>
      <div className="head">
        <span>{run.label} of 5</span>
        <span>{run.calls} calls</span>
      </div>
      {!visible && <div className="idle">waiting for the alert…</div>}
      {run.lines.map(([call, note, hit], i) => (
        // Lines stay mounted so CSS can fade them in one by one; under reduced motion there is no delay.
        <div key={run.key + i} className="call" style={reduce ? undefined : ({ '--i': i } as CSSProperties)}>
          → {call} <span>{note}</span> {hit && <span className="hit">{hit}</span>}
        </div>
      ))}
    </div>
  )
}

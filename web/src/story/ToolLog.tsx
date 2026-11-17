import type { CSSProperties } from 'react'
import type { StoryRun } from './types'

export function ToolLog({ run, visible }: { run: StoryRun; visible: boolean }) {
  return (
    <div className="log" data-visible={visible}>
      <div className="head">
        <span>{run.label} of 5</span>
        <span>{run.calls} calls, {run.lines.length} shown</span>
      </div>
      {!visible && <div className="idle">waiting for the alert…</div>}
      {run.lines.map(([call, note, hit], i) => (
        // Lines stay mounted so CSS can fade them in one by one (reduced motion: the global transition:none in site.css).
        <div key={run.key + i} className="call" aria-hidden={!visible} style={{ '--i': i } as CSSProperties}>
          → {call} <span>{note}</span> {hit && <span className="hit">{hit}</span>}
        </div>
      ))}
    </div>
  )
}

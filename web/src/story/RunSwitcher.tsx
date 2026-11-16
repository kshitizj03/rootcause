import type { StoryRun } from './types'

export function RunSwitcher({ runs, selected, onSelect }: { runs: StoryRun[]; selected: StoryRun['key']; onSelect: (key: StoryRun['key']) => void }) {
  return (
    <div className="runs-pick" role="group" aria-label="Which recorded run to show">
      {runs.map((r) => (
        <button key={r.key} type="button" aria-pressed={r.key === selected} onClick={() => onSelect(r.key)}>
          {r.short} <span className={r.ok ? 'r-ok' : 'r-bad'}>{r.ok ? '✓' : '✗'}</span>
        </button>
      ))}
    </div>
  )
}

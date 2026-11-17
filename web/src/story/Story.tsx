import { useState } from 'react'
import { ServiceMap } from '../map/ServiceMap'
import { RichText } from './RichText'
import { RunSwitcher } from './RunSwitcher'
import { ToolLog } from './ToolLog'
import { useActiveStep } from './useActiveStep'
import type { Story as StoryData, StoryRun } from './types'

export function Story({ story }: { story: StoryData }) {
  const [key, setKey] = useState<StoryRun['key']>(story.runs[0].key)
  const run = story.runs.find((r) => r.key === key) ?? story.runs[0]
  const { active, refs } = useActiveStep(story.steps.length)
  const last = story.steps.length
  const replay = `incident.html?id=${story.incident}&solver=${encodeURIComponent(run.solver)}&run=${run.run}`

  return (
    <div className="wrap" id="story">
      <div className="story">
        <div className="steps">
          {story.steps.map((s, i) => {
            const verdict = i + 1 === last
            return (
              <div key={i} ref={(el) => refs(el, i)} className={`step${active === i + 1 ? ' on' : ''}`}>
                <span className="eyebrow">{s.eyebrow}</span>
                <h2><RichText html={verdict ? run.verdictTitle : s.title} /></h2>
                <p><RichText html={verdict ? run.verdictText : s.body} /></p>
                {s.quote && <div className="quote">{s.quote}</div>}
                {verdict && <p className="replay"><a href={replay}>Replay this run, step by step →</a></p>}
              </div>
            )
          })}
        </div>
        <div className="stage">
          <ServiceMap variant="story" step={Math.min(active, 5) as 0 | 1 | 2 | 3 | 4 | 5} agentOk={run.ok} />
          <RunSwitcher runs={story.runs} selected={key} onSelect={setKey} />
          <ToolLog run={run} visible={active >= 4} />
        </div>
      </div>
    </div>
  )
}

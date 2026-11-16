import { motion, useReducedMotion } from 'motion/react'
import type { IndexData } from '../data/types'
import {
  overallOf, faultIncidents, mainSolvers, vsRuleRows, strength, heroAnswer, forestDomain, at, solverName, pct, signed, toolsOf,
} from '../lib/results'

const COLOUR = { clear: 'var(--ink)', suggestive: 'var(--mid)', none: 'var(--faint)' }
const VERDICT = { clear: 'clearly better than the rule', suggestive: 'suggestive', none: 'not distinguishable from the rule' }
const EASE = [0.22, 1, 0.36, 1] as const

export function Results({ data }: { data: IndexData }) {
  const reduced = useReducedMotion()
  const overall = overallOf(data)
  const rows = vsRuleRows(data, mainSolvers(data, overall))
  const dom = forestDomain(rows)
  const rule = overall.heuristic?.accuracy_mean
  return (
    <section className="results wrap" id="results">
      <span className="eyebrow">Across {faultIncidents(data).length} recorded outages</span>
      <h2 className="big">{heroAnswer(rows)}</h2>
      <p className="lede">
        Each agent's accuracy minus the rule's on the same incidents, with a 95% interval. Clearly better means the
        interval sits right of zero and an exact permutation test agrees; an interval right of zero without that is only suggestive.
      </p>
      <div className="forest">
        {rows.map((r, i) => {
          const st = strength(r)
          const l = at(r.ci[0], dom)
          const w = `${(parseFloat(at(r.ci[1], dom)) - parseFloat(l)).toFixed(2)}%`
          const z = at(0, dom)
          const delay = i * 0.07
          return (
            <div className="frow" data-strength={st} key={r.s}>
              <div className="nm">
                {solverName(r.s)}
                {st === 'suggestive' && <span className="tag">suggestive</span>}
                <small>
                  {pct(overall[r.s]?.accuracy_mean ?? 0)} right
                  {r.wins != null && r.losses != null && ` · won ${r.wins}, lost ${r.losses}`}
                </small>
              </div>
              <div className="track" role="img" aria-label={`${solverName(r.s)}: ${VERDICT[st]}, ${signed(r.mean)} (95% interval ${signed(r.ci[0])} to ${signed(r.ci[1])})`}
                style={{ '--c': COLOUR[st] } as React.CSSProperties}>
                <span className="zero" style={{ left: z }} />
                {reduced ? (
                  <span className="bar" style={{ left: l, width: w }} />
                ) : (
                  <motion.span className="bar" style={{ left: z, width: 0 }}
                    whileInView={{ left: l, width: w }} viewport={{ once: true, margin: '-10% 0px' }}
                    transition={{ duration: 1.1, ease: EASE, delay }} />
                )}
                {reduced ? (
                  <span className={`dot${toolsOf(r.s) === 'v0' ? ' hollow' : ''}`} style={{ left: at(r.mean, dom) }} />
                ) : (
                  <motion.span className={`dot${toolsOf(r.s) === 'v0' ? ' hollow' : ''}`}
                    style={{ left: at(r.mean, dom) }} initial={{ opacity: 0, scale: 0.3 }}
                    whileInView={{ opacity: 1, scale: 1 }} viewport={{ once: true, margin: '-10% 0px' }}
                    transition={{ duration: 0.5, ease: EASE, delay: delay + 0.7 }} />
                )}
              </div>
              <div className="num">{signed(r.mean)}</div>
            </div>
          )
        })}
        <div className="axis">
          <span>{rule != null ? `rule: ${pct(rule)}` : ''}</span>
          <span className="ends"><span>← worse than the rule</span><span>better →</span></span>
          <span />
        </div>
      </div>
      <div className="legend">
        <span><i style={{ background: 'var(--ink)' }} />clearly better than the rule</span>
        <span><i style={{ background: 'var(--mid)' }} />suggestive</span>
        <span><i style={{ background: 'var(--faint)' }} />not distinguishable</span>
      </div>
    </section>
  )
}

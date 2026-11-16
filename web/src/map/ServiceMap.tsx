import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { EDGES, FULL_VIEWBOX, LIT, NODES, PATH, PHONE_LABELS, PHONE_VIEWBOX, type ServiceId } from './layout'
import './map.css'

type Step = 0 | 1 | 2 | 3 | 4 | 5

const curve = ([x1, y1]: [number, number], [x2, y2]: [number, number]) =>
  `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`

function describe(step: Step, agentOk: boolean): string {
  const parts = ["The shop's services and the calls between them"]
  if (step >= 1) parts.push('valkey-cart, the cause, is down')
  if (step >= 2) parts.push('cart, the symptom, is slow, and errors reach frontend, checkout and payment')
  if (step >= 3) parts.push('the rule names cart')
  if (step >= 4) parts.push('the agent follows the failing calls from frontend to cart to valkey-cart')
  if (step >= 5) parts.push(agentOk ? 'the agent names valkey-cart, which is right' : 'the agent names cart, which is wrong')
  return parts.join('; ')
}

const MARKS = [
  { cls: 'm-rule', x: 298, y: 207, label: '✗ rule: cart', color: 'var(--warn)' },
  { cls: 'm-agent ok-mark', x: 470, y: 196, label: '✓ agent: valkey-cart', color: 'var(--ok)' },
  { cls: 'm-agent bad-mark', x: 236, y: 276, label: '✗ agent: cart', color: 'var(--fault)' },
]

export function ServiceMap({ variant, step = 0, agentOk = true }: { variant: 'hero' | 'story'; step?: Step; agentOk?: boolean }) {
  const story = variant === 'story'
  const ref = useRef<SVGSVGElement>(null)
  const [phone] = useState(() => story && window.matchMedia('(max-width: 860px)').matches)

  // Size each tag to its text once fonts are in. jsdom has no getBBox, so feature-detect.
  useEffect(() => {
    if (!story) return
    let live = true
    void document.fonts?.ready.then(() => {
      if (!live) return
      ref.current?.querySelectorAll<SVGGElement>('.mark').forEach((m) => {
        const text = m.querySelector('text')
        if (text && 'getBBox' in text) m.querySelector('rect')?.setAttribute('width', String(text.getBBox().width + 18))
      })
    })
    return () => { live = false }
  }, [story])

  const labelled = (id: ServiceId) => story && (!phone || PHONE_LABELS.includes(id))
  return (
    <svg
      ref={ref}
      data-step={step}
      data-ok={agentOk ? 1 : 0}
      viewBox={phone ? PHONE_VIEWBOX : FULL_VIEWBOX}
      className={story ? 'map map-story' : 'map'}
      {...(story ? { role: 'img', 'aria-label': describe(step, agentOk) } : { 'aria-hidden': true })}
    >
      {EDGES.map(([a, b]) => (
        <path key={a + b} className={`edge e-${a}-${b}${PATH.has(`${a}>${b}`) ? ' path' : ''}`} d={curve(NODES[a], NODES[b])} />
      ))}
      {(Object.entries(NODES) as [ServiceId, [number, number]][]).map(([k, [x, y]]) => (
        <g key={k} className={`node n-${k}${k in LIT ? ' lit' : ''}`} style={{ '--d': `${LIT[k] ?? 0}s` } as CSSProperties}>
          <circle className="ring" cx={x} cy={y} r={9} />
          <circle className="core" cx={x} cy={y} r={8} />
          {labelled(k) && <text x={x} y={y + 24} textAnchor="middle">{k}</text>}
        </g>
      ))}
      {story && MARKS.map((m) => (
        <g key={m.cls} className={`mark ${m.cls}`}>
          <rect x={m.x} y={m.y} width={m.label.length * 7.6 + 18} height={24} fill={m.color} />
          <text x={m.x + 9} y={m.y + 16} fill="var(--on-mark)">{m.label}</text>
        </g>
      ))}
    </svg>
  )
}

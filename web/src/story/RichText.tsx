import type { ReactNode } from 'react'

// Only these exact forms become elements; everything else (including other tags) stays literal text.
const ALLOWED = /(<span class="(?:ok|bad)">[^<]*<\/span>|<strong>[^<]*<\/strong>)/
const SPAN = /^<span class="(ok|bad)">([^<]*)<\/span>$/
const STRONG = /^<strong>([^<]*)<\/strong>$/

export function RichText({ html }: { html: string }): ReactNode {
  return html.split(ALLOWED).map((part, i) => {
    const span = SPAN.exec(part)
    if (span) return <span key={i} className={span[1]}>{span[2]}</span>
    const strong = STRONG.exec(part)
    if (strong) return <strong key={i}>{strong[1]}</strong>
    return part
  })
}

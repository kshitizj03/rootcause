const MOVED = ['#every-run', '#findings', '#by-type', '#reproduce', '#result']

/** The old landing page's sections now live on results.html: where a shared old link should go, or null. */
export const oldAnchorRedirect = (hash: string): string | null => (MOVED.includes(hash) ? `results.html${hash}` : null)

import type { IndexData } from '../data/types'
import { isPartial, type Overall } from '../lib/results'

export const GRID_SOLVERS = [
  'heuristic',
  'claude-code-opus-5.5',
  'agent-v1@nvidia-nemotron-3-ultra-550b-a55b',
  'agent-v1@z-ai-glm-5.3-flash',
]

/** The ids this release has as complete batches. */
export const availableSolvers = (data: IndexData, overall: Overall, ids: string[]): string[] =>
  ids.filter((s) => data.solvers.includes(s) && !isPartial(data, s, overall))

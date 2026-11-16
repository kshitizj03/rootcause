import type { IncidentRow, IndexData, Pair, SummaryRow } from "../data/types";

const HEUR = "heuristic";
const OPUS = "claude-code-opus-5.5";
const NEMO = "agent-v1-nemotron";
const PART = "agent-v1-nemotron-vague";
const AGENTS = [OPUS, NEMO, PART];
const SOLVERS = [HEUR, ...AGENTS];

const row = (
  id: string,
  category: string,
  truth: IncidentRow["truth"],
  results: IncidentRow["results"],
): IncidentRow => ({
  id,
  category,
  alert: `Alert for ${id}.`,
  heldout: false,
  heldout_viewed: false,
  truth,
  results,
});

const summaryRow = (category: string, mean: number, scenarios: number, runs: number): SummaryRow => ({
  category,
  accuracy_mean: mean,
  accuracy_std: runs > 1 ? 0.1 : null,
  scenarios,
  expected: scenarios,
  runs,
});

const pair = (a: string, mean_diff: number, ci: [number, number], p: number, wins: number, losses: number): Pair => ({
  a,
  b: HEUR,
  n: 2,
  mean_diff,
  ci,
  p,
  wins,
  losses,
  with_controls: { n: 3, mean_diff: mean_diff * 0.7, ci: [ci[0] * 0.8, ci[1] * 0.8] },
});

/** A fresh, small, valid index on every call, safe to mutate. */
export function fixtureIndex(): IndexData {
  return {
    categories: ["easy", "hard-silent", "control"],
    generated: "2026-11-16",
    incidents: [
      row("ad-failure", "easy", [{ accept: ["ad"], fault_type: "errors" }], {
        [HEUR]: [1],
        [OPUS]: [1, 1, 1, 1, 1],
        [NEMO]: [1, 1, 1, 0.5, 1],
        [PART]: [1, 1, 1, 1, 1],
      }),
      row("cart-silent", "hard-silent", [{ accept: ["cart"], fault_type: "latency" }], {
        [HEUR]: [0],
        [OPUS]: [1, 1, 0.5, 1, 1],
        [NEMO]: [0, 0.5, 0, 0, 0.5],
        [PART]: [0, 0, 0],
      }),
      row("quiet-night", "control", [], {
        [HEUR]: [1],
        [OPUS]: [1, 1, 1, 1, 1],
        [NEMO]: [1, 1, 1, 1, 1],
        [PART]: [1, 1, 1, 1, 1],
      }),
    ],
    paired: [
      pair(OPUS, 0.9, [0.5, 1], 0.03, 2, 0),
      pair(NEMO, 0.25, [-0.2, 0.7], 0.31, 1, 1),
      pair(PART, -0.1, [-0.6, 0.4], 0.62, 0, 1),
    ],
    planned_runs: { [HEUR]: 1, [OPUS]: 5, [NEMO]: 5, [PART]: 5 },
    solvers: SOLVERS,
    summary: {
      [HEUR]: [summaryRow("easy", 1, 1, 1), summaryRow("hard-silent", 0, 1, 1), summaryRow("control", 1, 1, 1), summaryRow("all incidents", 0.5, 2, 1)],
      [OPUS]: [summaryRow("easy", 1, 1, 5), summaryRow("hard-silent", 0.9, 1, 5), summaryRow("control", 1, 1, 5), summaryRow("all incidents", 0.95, 2, 5)],
      [NEMO]: [summaryRow("easy", 0.9, 1, 5), summaryRow("hard-silent", 0.2, 1, 5), summaryRow("control", 1, 1, 5), summaryRow("all incidents", 0.55, 2, 5)],
      [PART]: [summaryRow("easy", 1, 1, 5), summaryRow("hard-silent", 0, 1, 3), summaryRow("control", 1, 1, 5), summaryRow("all incidents", 0.5, 2, 4)],
    },
    coverage: {},
  };
}

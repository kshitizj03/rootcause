// The pure results logic behind the landing page, ported from site/assets/lib.js (names, marks, chart encoding,
// the vs-the-rule comparison). No DOM.
import type { IncidentRow, IndexData, Interval, SummaryRow } from "../data/types";

export type Overall = Record<string, SummaryRow | undefined>;

export interface VsRuleRow {
  s: string;
  mean: number;
  ci: Interval;
  n: number;
  p?: number;
  wins?: number;
  losses?: number;
}

type Label = [name: string, sub: string];

const CATEGORIES: Record<string, Label> = {
  easy: ["Easy", "one loud fault"],
  "hard-cross-service": ["Cross-service", "the symptom shows up in a different service from the cause"],
  "hard-silent": ["Silent", "latency or resource faults with no errors"],
  "hard-noisy": ["Noisy", "a real fault plus a decoy traffic flood"],
  "hard-two-faults": ["Two-fault", "both causes must be named"],
  control: ["Control", "nothing is broken; the right answer is “no incident”"],
};

export const SOLVERS: Record<string, Label> = {
  heuristic: ["Heuristic", "the simple rule"],
  "agent-v0": ["V0 on Gemini Flash-Lite", "naive tools, Gemini 3.5 Flash-Lite"],
  "agent-v1": ["V1 on Gemini Flash-Lite", "change-aware tools, Gemini 3.5 Flash-Lite"],
  "agent-v1-nopriors": ["V1 on Gemini Flash-Lite (no priors)", "ablation: two prompt sentences removed"],
  "agent-v1-vague": ["V1 on Gemini Flash-Lite (vague alerts)", "ablation: one generic alert"],
  "agent-v0-nemotron": ["V0 on Nemotron 3 Super", "naive tools, Nemotron 3 Super"],
  "agent-v1-nemotron": ["V1 on Nemotron 3 Super", "change-aware tools, Nemotron 3 Super"],
  "agent-v1-nemotron-nopriors": ["V1 on Nemotron 3 Super (no priors)", "ablation: two prompt sentences removed"],
  "agent-v1-nemotron-vague": ["V1 on Nemotron 3 Super (vague alerts)", "ablation: one generic alert"],
  "agent-v1-nemotron-steps30": ["V1 on Nemotron 3 Super (30 steps)", "ablation: twice the step limit"],
  "agent-v1@z-ai-glm-5.3-flash": ["V1 on GLM 5.3 Flash", "change-aware tools, GLM 5.3 Flash"],
  "agent-v0@nvidia-nemotron-3.5-super-vl-120b-a12b": ["V0 on Nemotron 3.5 Super", "naive tools, Nemotron 3.5 Super"],
  "agent-v1@nvidia-nemotron-3.5-super-vl-120b-a12b": ["V1 on Nemotron 3.5 Super", "change-aware tools, Nemotron 3.5 Super"],
  "agent-v1@nvidia-nemotron-3-ultra-550b-a55b": ["V1 on Nemotron 3 Ultra", "change-aware tools, Nemotron 3 Ultra"],
  "agent-v1@nvidia-nemotron-3.5-lightning-30b-a3b": ["V1 on Nemotron 3.5 Lightning", "change-aware tools, Nemotron 3.5 Lightning"],
  "claude-code-sonnet-5.5": ["Claude Sonnet 5.5", "v1 prompt and tools, in Claude Code's loop"],
  "claude-code-opus-5.5": ["Claude Opus 5.5", "v1 prompt and tools, in Claude Code's loop"],
};

const GEMINI = "Gemini 3.5 Flash-Lite";
const GEMINI_NAME = " on Gemini Flash-Lite"; // in the names; a base@model record swaps the model in

/** A built-in solver's label; a built-in one run on another model (records named base@model, the base always a
 * Gemini solver) with that model in place of Gemini; anything else (your own agent) by its record name, as custom. */
function label(s: string): Label {
  const known = SOLVERS[s];
  if (known) return known;
  const [base, model] = s.split("@");
  const built = SOLVERS[base];
  if (model && built) {
    const [name, sub] = built;
    return [
      name.includes(GEMINI_NAME) ? name.replace(GEMINI_NAME, ` on ${model}`) : `${name} on ${model}`,
      sub.replace(GEMINI, "another model"),
    ];
  }
  return [s, "custom"];
}

export const solverName = (s: string): string => label(s)[0];
export const solverSub = (s: string): string => label(s)[1];
export const categoryName = (c: string): string => (CATEGORIES[c] ?? [c])[0];
export const pct = (x: number): string => `${Math.round(x * 100)}%`;

/** +0.26 / −0.12, with a true minus sign; a value that rounds to zero is +0.00. */
export const signed = (x: number): string => {
  const t = Math.abs(x).toFixed(2);
  return `${x < 0 && t !== "0.00" ? "−" : "+"}${t}`;
};

/** A run's score as a mark: 1 is correct, 0 wrong, anything between partly correct (two-fault, one cause of two). */
export function mark(correct: number): { cls: "hit" | "part" | "miss"; glyph: string; word: string } {
  if (correct >= 1) return { cls: "hit", glyph: "✓", word: "correct" };
  if (correct > 0) return { cls: "part", glyph: "½", word: "partly correct" };
  return { cls: "miss", glyph: "✗", word: "wrong" };
}

/** The model a solver runs on, for its chart colour: rule (the heuristic), gemini, nemotron, nemotron35, ultra,
 * lightning, glm, claude, or other. */
export function modelOf(s: string): string {
  if (s === "heuristic") return "rule";
  if (s.startsWith("claude-code-")) return "claude";
  const [base, model = ""] = s.split("@");
  if (/glm/i.test(model)) return "glm";
  if (/nemotron-3-ultra/i.test(model)) return "ultra";
  if (/nemotron-3\.5-lightning/i.test(model)) return "lightning";
  if (/nemotron-3\.5/i.test(model)) return "nemotron35";
  if (model) return "other";
  if (!base.startsWith("agent")) return "other";
  return base.includes("nemotron") ? "nemotron" : "gemini";
}

/** "v0" (naive tools), "v1" (change-aware tools), or null for the heuristic and others. */
export const toolsOf = (s: string): "v0" | "v1" | null => (/^agent-v0/.test(s) ? "v0" : /^agent-v1/.test(s) ? "v1" : null);

export const isAblation = (s: string): boolean => /-(nopriors|vague|steps30)(@|$)/.test(s);

/** Each solver's "all incidents" summary row. */
export const overallOf = (data: IndexData): Overall =>
  Object.fromEntries(data.solvers.map((s) => [s, data.summary[s]?.find((r) => r.category === "all incidents")]));

/** Whether a solver's batch is partial: fewer than its planned runs on some incident, or incidents missing. */
export function isPartial(data: IndexData, s: string, overall: Overall): boolean {
  const counts = data.incidents.map((i) => (i.results[s] ?? []).length);
  const planned = data.planned_runs[s];
  const o = overall[s];
  const n = o?.expected ?? o?.scenarios;
  return Boolean((planned && Math.min(...counts) < planned) || !o || (n !== undefined && o.scenarios < n));
}

/** The complete, non-ablation batches: the heuristic first, then the rest, most accurate first. */
export const mainSolvers = (data: IndexData, overall: Overall): string[] =>
  data.solvers
    .filter((s) => overall[s] && !isAblation(s) && !isPartial(data, s, overall))
    .sort((x, y) => Number(y === "heuristic") - Number(x === "heuristic")
      || (overall[y]?.accuracy_mean ?? 0) - (overall[x]?.accuracy_mean ?? 0));

/** Recorded runs over every complete solver except the heuristic, ablations included. */
export const investigationCount = (data: IndexData, overall: Overall): number =>
  data.solvers
    .filter((s) => s !== "heuristic" && !isPartial(data, s, overall))
    .reduce((t, s) => t + data.incidents.reduce((u, i) => u + (i.results[s] ?? []).length, 0), 0);

export const faultIncidents = (data: IndexData): IncidentRow[] => data.incidents.filter((i) => i.category !== "control");

/** Runs that scored in full. */
export const rightOf = (results: number[]): number => results.filter((r) => r >= 1).length;

/** Each complete agent against the heuristic on the fault incidents, best first. Pairs without an interval are left out. */
export function vsRuleRows(data: IndexData, complete: string[]): VsRuleRow[] {
  const rows: VsRuleRow[] = [];
  for (const p of data.paired) {
    if (p.b === "heuristic" && p.ci && complete.includes(p.a)) {
      rows.push({ s: p.a, mean: p.mean_diff, ci: p.ci, n: p.n, p: p.p, wins: p.wins, losses: p.losses });
    }
  }
  return rows.sort((x, y) => y.mean - x.mean);
}

/** Clearly better only when the 95% interval lies above 0 and the permutation test agrees (p <= 0.05); above 0 with a
 * larger p is suggestive. A row without p (an older index.json) goes by the interval. */
export const strength = (r: Pick<VsRuleRow, "ci" | "p">): "clear" | "suggestive" | "none" =>
  r.ci[0] <= 0 ? "none" : r.p == null || r.p <= 0.05 ? "clear" : "suggestive";

/** The hero's one-line answer, naming no vendor: none, some or all of the agents clearly better. */
export function heroAnswer(rows: VsRuleRow[]): string {
  const clear = rows.filter((r) => strength(r) === "clear").length;
  return !clear ? "Not clearly." : clear < rows.length ? "Only the strongest models." : "Yes, by more than the noise.";
}

/** A symmetric axis around 0 that holds every interval, in steps of 0.1: [-m, m]. */
export function forestDomain(rows: { ci: Interval; controls?: { ci: Interval } | null }[]): Interval {
  const ends = rows.flatMap((r) => [...r.ci, ...(r.controls ? r.controls.ci : [])].map(Math.abs));
  const m = Math.ceil(Math.max(0.1, ...ends) * 10 + 0.5) / 10;
  return [-m, m];
}

/** Percentage position of value v on [lo, hi], clamped to the track. */
export const at = (v: number, [lo, hi]: Interval): string =>
  `${(Math.min(1, Math.max(0, (v - lo) / (hi - lo))) * 100).toFixed(2)}%`;

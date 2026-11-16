export interface Truth {
  accept: string[];
  fault_type: string;
}

export interface IncidentRow {
  id: string;
  category: string;
  alert: string;
  heldout: boolean;
  heldout_viewed?: boolean;
  truth: Truth[];
  /** One score per recorded run: 1, 0.5 or 0. */
  results: Record<string, number[]>;
}

export interface SummaryRow {
  category: string;
  accuracy_mean: number;
  /** null for solvers with a single run per incident (the heuristic). */
  accuracy_std: number | null;
  scenarios: number;
  expected?: number;
  runs: number;
}

export type Interval = [number, number];

export interface Pair {
  a: string;
  b: string;
  n: number;
  mean_diff: number;
  ci: Interval | null;
  p?: number;
  wins?: number;
  losses?: number;
  with_controls: { n: number; mean_diff: number; ci: Interval | null };
}

export interface IndexData {
  categories: string[];
  generated: string;
  incidents: IncidentRow[];
  paired: Pair[];
  planned_runs: Record<string, number>;
  solvers: string[];
  summary: Record<string, SummaryRow[]>;
  coverage: Record<string, { accuracy: number; coverage: number; threshold: number }[]>;
}

export interface Step {
  tool: string;
  args: Record<string, unknown>;
  output: unknown;
}

export interface RunRecord {
  causes: { service: string; fault_type: string }[];
  confidence: number;
  steps: Step[];
  score: { correct: number };
  run: number;
}

export interface IncidentFile {
  id: string;
  alert: string;
  truth: Truth[];
  runs: Record<string, RunRecord[]>;
}

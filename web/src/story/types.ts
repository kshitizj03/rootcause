/** [call, note, hit]: one line of a run's tool-call log. hit is the highlighted result, or "". */
export type LogLine = [call: string, note: string, hit: string];

export interface StoryRun {
  key: "a" | "b" | "c";
  label: string;
  short: string;
  solver: string;
  /** 1-based, as shown on the replay page. */
  run: number;
  ok: boolean;
  calls: number;
  topCause: string;
  secondCause?: string;
  confidence: number;
  lines: LogLine[];
  /** May contain <span class="ok|bad"> and <strong>; render with an allow-listed renderer. */
  verdictTitle: string;
  verdictText: string;
}

export interface StoryStep {
  eyebrow: string;
  /** May contain <span class="ok|bad"> markup. */
  title: string;
  /** May contain <strong> markup. */
  body: string;
  quote?: string;
}

/** Every number the copy quotes; valkey-cart.claims.test.ts checks them against the run data. */
export interface StoryFacts {
  cartP95: { before: number; after: number; change: string };
  failedCalls: { caller: string; callee: string; errors: number; calls: number };
  storageError: string;
  spreadTo: string[];
  rightOutOf5: Record<string, number>;
  /** Displayed rule accuracy over fault incidents (0.59 = 59%). */
  ruleFaultAccuracy: number;
}

export interface Story {
  incident: string;
  steps: StoryStep[];
  runs: StoryRun[];
  facts: StoryFacts;
}

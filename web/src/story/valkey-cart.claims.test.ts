import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { IncidentFile, IndexData, Step } from "../data/types";
import { overallOf, rightOf } from "../lib/results";
import { STORY } from "./valkey-cart";

// Resolved from process.cwd() (vitest runs from web/): under jsdom import.meta.url is not a file: URL.
const dataDir = resolve(process.cwd(), "../site/data");
const incidentPath = resolve(dataDir, "incidents/valkey-cart-paused.json");
const indexPath = resolve(dataDir, "index.json");
const have = existsSync(incidentPath) && existsSync(indexPath);

// Change entries are tolerated loosely: the tool output is parsed JSON of unknown shape.
type Change = { service: string; signal: string; before: number; after: number; change: string };

describe.skipIf(!have)("valkey-cart story claims", () => {
  const file = (have ? JSON.parse(readFileSync(incidentPath, "utf8")) : null) as IncidentFile;
  const index = (have ? JSON.parse(readFileSync(indexPath, "utf8")) : null) as IndexData;
  const runA = STORY.runs.find((r) => r.key === "a")!;
  const stepsA: Step[] = file?.runs[runA.solver][runA.run - 1].steps ?? [];
  const firstOf = (tool: string, pred: (s: Step) => boolean = () => true) => stepsA.find((s) => s.tool === tool && pred(s));
  const topChanges = () => (firstOf("top_changes")!.output as { changes: Change[] }).changes;

  it("each run's verdict, top cause, confidence and call count match the record", () => {
    for (const r of STORY.runs) {
      const rec = file.runs[r.solver][r.run - 1];
      expect(rec.score.correct >= 1, r.key).toBe(r.ok);
      expect(rec.causes[0].service, r.key).toBe(r.topCause);
      if (r.secondCause) expect(rec.causes[1]?.service, r.key).toBe(r.secondCause);
      expect(rec.confidence, r.key).toBe(r.confidence);
      expect(rec.steps.length, r.key).toBe(r.calls);
    }
  });

  it("cart's p95 numbers come from top_changes", () => {
    expect(topChanges()).toContainEqual(
      expect.objectContaining({ service: "cart", signal: "p95_ms", before: STORY.facts.cartP95.before, after: STORY.facts.cartP95.after, change: STORY.facts.cartP95.change }),
    );
  });

  // Every run the story shows quotes the same clues, so check them for all three.
  const stepsOf = (r: (typeof STORY.runs)[number]): Step[] => file.runs[r.solver][r.run - 1].steps;

  it("the failed calls come from service_map", () => {
    const { caller, callee, errors, calls } = STORY.facts.failedCalls;
    for (const r of STORY.runs) {
      const map = stepsOf(r).find((s) => s.tool === "service_map")!;
      const edges = (map.output as { edges: { caller: string; callee: string; errors_after: number; calls_after: number }[] }).edges;
      expect(edges, r.key).toContainEqual(expect.objectContaining({ caller, callee, errors_after: errors, calls_after: calls }));
    }
  });

  it("the storage error comes from the traces", () => {
    for (const r of STORY.runs) {
      const found = stepsOf(r)
        .filter((s) => s.tool === "search_traces")
        .some((s) => Object.keys((s.output as { error_messages?: Record<string, number> }).error_messages ?? {}).some((m) => m.includes(STORY.facts.storageError)));
      expect(found, r.key).toBe(true);
    }
  });

  it("errors spread to payment and checkout", () => {
    for (const svc of STORY.facts.spreadTo) {
      expect(topChanges().some((c) => c.service === svc && c.signal === "error_ratio"), svc).toBe(true);
    }
  });

  it("valkey-cart barely changes", () => {
    const h = firstOf("service_health", (s) => s.args.service === "valkey-cart")!;
    const signals = (h.output as { signals: Change[] }).signals;
    expect(signals.length).toBeGreaterThan(0);
    for (const s of signals) expect(Math.abs(parseFloat(s.change)), s.signal).toBeLessThan(1);
  });

  it("right-out-of-5 counts match the index", () => {
    const row = index.incidents.find((i) => i.id === STORY.incident)!;
    for (const [s, n] of Object.entries(STORY.facts.rightOutOf5)) expect(rightOf(row.results[s]), s).toBe(n);
  });

  it("the rule's accuracy and the fault-incident count match the index", () => {
    expect(Math.round(overallOf(index).heuristic!.accuracy_mean * 100)).toBe(Math.round(STORY.facts.ruleFaultAccuracy * 100));
    expect(index.incidents.filter((i) => i.category !== "control")).toHaveLength(16);
  });
});

import { describe, expect, test } from "vitest";
import { fixtureIndex } from "../test/fixture";
import type { IncidentRow, IndexData, Interval, Pair, SummaryRow } from "../data/types";
import {
  at, categoryName, faultIncidents, forestDomain, heroAnswer, investigationCount, isAblation, isPartial, mainSolvers,
  mark, modelOf, overallOf, pct, rightOf, signed, solverName, solverSub, strength, toolsOf, vsRuleRows,
  type Overall, type VsRuleRow,
} from "./results";

const inc = (results: Record<string, number[]>, category = "easy"): IncidentRow => ({
  id: "x", category, alert: "", heldout: false, truth: [], results,
});
const idx = (o: Partial<IndexData>): IndexData => ({ ...fixtureIndex(), incidents: [], paired: [], planned_runs: {}, solvers: [], ...o });
const sum = (accuracy_mean: number, scenarios: number, expected = 16): SummaryRow =>
  ({ category: "all incidents", accuracy_mean, accuracy_std: null, scenarios, expected, runs: 1 });
const pr = (a: string, mean_diff: number, ci: Interval | null, b = "heuristic", p?: number): Pair =>
  ({ a, b, n: 16, mean_diff, ci, p, with_controls: { n: 20, mean_diff, ci } });

describe("names and numbers", () => {
  test("names: known solvers and categories, unknown ones by their record name", () => {
    expect(solverName("agent-v1-nemotron")).toBe("V1 on Nemotron 3 Super");
    expect(solverName("my-agent")).toBe("my-agent");
    expect(solverSub("my-agent")).toBe("custom");
    expect(solverSub("agent-v1")).toBe("change-aware tools, Gemini 3.5 Flash-Lite");
    expect(categoryName("hard-silent")).toBe("Silent");
    expect(categoryName("new-kind")).toBe("new-kind");
  });

  test("names: a built-in agent on another model names that model, not Gemini", () => {
    expect(solverName("agent-v1@qwen-9b")).toBe("V1 on qwen-9b");
    expect(solverSub("agent-v1@qwen-9b")).toBe("change-aware tools, another model");
    expect(solverName("agent-v1@z-ai-glm-5.3-flash")).toBe("V1 on GLM 5.3 Flash");
    expect(solverName("agent-v1-vague@m")).toBe("V1 on m (vague alerts)");
    expect(solverSub("my-agent@m")).toBe("custom");
  });

  test("signed: true minus, and zero is +0.00", () => {
    expect(signed(0.26)).toBe("+0.26");
    expect(signed(-0.12)).toBe("−0.12");
    expect(signed(-0.004)).toBe("+0.00");
  });

  test("pct", () => {
    expect(pct(0.594)).toBe("59%");
  });

  test("mark: 1 hit, 0.5 part, 0 miss", () => {
    expect(mark(1).cls).toBe("hit");
    expect(mark(0.5)).toEqual({ cls: "part", glyph: "½", word: "partly correct" });
    expect(mark(0).cls).toBe("miss");
  });
});

describe("charts", () => {
  test("chart encoding: hue is the model, fill is the toolset", () => {
    expect(modelOf("heuristic")).toBe("rule");
    expect(modelOf("agent-v1")).toBe("gemini");
    expect(modelOf("agent-v0-nemotron")).toBe("nemotron");
    expect(modelOf("agent-v1@z-ai-glm-5.3-flash")).toBe("glm");
    expect(modelOf("agent-v1@nvidia-nemotron-3.5-super-vl-120b-a12b")).toBe("nemotron35");
    expect(modelOf("claude-code-opus-5.5")).toBe("claude");
    expect(modelOf("agent-v1@nvidia-nemotron-3-ultra-550b-a55b")).toBe("ultra");
    expect(modelOf("agent-v1@nvidia-nemotron-3.5-lightning-30b-a3b")).toBe("lightning");
    expect(toolsOf("claude-code-opus-5.5")).toBeNull();
    expect(modelOf("agent-v1@qwen-9b")).toBe("other");
    expect(modelOf("my-agent")).toBe("other");
    expect(toolsOf("agent-v0-nemotron")).toBe("v0");
    expect(toolsOf("agent-v1-nemotron-vague")).toBe("v1");
    expect(toolsOf("heuristic")).toBeNull();
    expect(isAblation("agent-v1-nemotron-steps30") && isAblation("agent-v1-vague@m") && !isAblation("agent-v1-nemotron")).toBe(true);
  });

  const GLM = "agent-v1@z-ai-glm-5.3-flash";
  const chartData = (): IndexData => idx({
    solvers: ["heuristic", "agent-v1", "agent-v1-nemotron", "agent-v1-nemotron-vague", GLM],
    planned_runs: { heuristic: 1, "agent-v1": 5, "agent-v1-nemotron": 5, "agent-v1-nemotron-vague": 5, [GLM]: 5 },
    incidents: [inc({ heuristic: [1], "agent-v1": [1, 1, 1, 1, 1], "agent-v1-nemotron": [1, 1, 1, 1, 1],
      "agent-v1-nemotron-vague": [1, 1, 1, 1, 1], [GLM]: [1, 1] })],
    paired: [
      pr("agent-v1", -0.18, [-0.4, 0.02]),
      pr("agent-v1-nemotron", 0.08, [-0.05, 0.23]),
      pr(GLM, 0.2, [0.1, 0.3]),
      pr("agent-v1-nemotron-vague", -0.12, [-0.25, -0.01], "agent-v1-nemotron"),
      pr("agent-v1-nemotron", 0.26, [0.1, 0.44], "agent-v1"),
    ],
  });
  const flat = (d: IndexData): Overall => Object.fromEntries(d.solvers.map((s) => [s, sum(0.5, 1, 1)]));

  test("main batches: complete and not ablations; a partial batch is left out", () => {
    const d = chartData();
    expect(isPartial(d, GLM, flat(d))).toBe(true);
    expect(mainSolvers(d, flat(d))).toEqual(["heuristic", "agent-v1", "agent-v1-nemotron"]);
  });

  test("vs the rule: complete agents only, best first", () => {
    const d = chartData();
    expect(vsRuleRows(d, mainSolvers(d, flat(d))).map((r) => r.s)).toEqual(["agent-v1-nemotron", "agent-v1"]);
  });

  test("forest axis: symmetric around 0, holds every interval, positions clamp to the track", () => {
    expect(forestDomain([{ ci: [-0.4, 0.02] }, { ci: [0.1, 0.44] }])).toEqual([-0.5, 0.5]);
    expect(forestDomain([{ ci: [-0.05, 0.03], controls: { ci: [-0.3, 0.1] } }])).toEqual([-0.4, 0.4]);
    expect(at(0, [-0.5, 0.5])).toBe("50.00%");
    expect(at(0.9, [-0.5, 0.5])).toBe("100.00%");
  });

  test("hero: clear needs the interval above 0 and p <= 0.05; the answer names no vendor", () => {
    const row = (s: string, lo: number, p?: number): VsRuleRow => ({ s, mean: lo + 0.2, ci: [lo, lo + 0.4], n: 16, p });
    expect(strength(row("x", -0.1, 0.5))).toBe("none");
    expect(strength(row("x", 0.02, 0.09))).toBe("suggestive");
    expect(strength(row("x", 0.09, 0.03))).toBe("clear");
    expect(strength(row("x", 0.09, undefined))).toBe("clear");
    const opus = row("claude-code-opus-5.5", 0.09, 0.03), ultra = row("agent-v1@nvidia-nemotron-3-ultra-550b-a55b", 0.02, 0.09);
    expect(heroAnswer([opus, ultra])).toBe("Only the strongest models.");
    expect(heroAnswer([ultra])).toBe("Not clearly.");
    expect(heroAnswer([opus, row("agent-v1", 0.05, 0.01)])).toBe("Yes, by more than the noise.");
  });

  test("main solvers: the rule first, then most accurate first", () => {
    const data = idx({ solvers: ["agent-v0", "heuristic", "agent-v1"], incidents: [inc({})] });
    const overall: Overall = { heuristic: sum(0.6, 16), "agent-v0": sum(0.5, 16), "agent-v1": sum(0.9, 16) };
    expect(mainSolvers(data, overall)).toEqual(["heuristic", "agent-v1", "agent-v0"]);
  });
});

describe("helpers from the fixture", () => {
  test("overallOf picks each solver's all-incidents row", () => {
    const d = fixtureIndex();
    const o = overallOf(d);
    expect(Object.keys(o).sort()).toEqual([...d.solvers].sort());
    expect(o["claude-code-opus-5.5"]?.accuracy_mean).toBe(0.95);
    expect(o.heuristic?.category).toBe("all incidents");
    d.summary.heuristic = d.summary.heuristic.filter((r) => r.category !== "all incidents");
    expect(overallOf(d).heuristic).toBeUndefined();
  });

  test("investigationCount counts complete agents only", () => {
    const d = fixtureIndex();
    // opus 3 incidents x 5 runs + nemotron 3 x 5 = 30; the partial vague agent and the heuristic are excluded
    expect(investigationCount(d, overallOf(d))).toBe(30);
  });

  test("faultIncidents leaves out controls", () => {
    expect(faultIncidents(fixtureIndex()).map((i) => i.id)).toEqual(["ad-failure", "cart-silent"]);
  });

  test("rightOf counts only full scores", () => {
    expect(rightOf([1, 0.5, 0, 1])).toBe(2);
  });
});

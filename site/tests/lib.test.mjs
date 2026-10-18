// node --test "site/tests/*.test.mjs"
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  solverName, solverSub, categoryName, pct, signed, plural, num, minutes, counted, mark,
  stripSlots, strip, answerText, pairedText, alertFor, sparkGeometry, logsLine, trimNotes, argText, evidenceText,
} from "../assets/lib.js";

// ---------------------------------------------------------------- names and numbers

test("names: known solvers and categories, unknown ones by their record name", () => {
  assert.equal(solverName("agent-v1-nemotron"), "V1 on Nemotron");
  assert.equal(solverName("my-agent"), "my-agent");
  assert.equal(solverSub("my-agent"), "custom");
  assert.equal(solverSub("agent-v1"), "change-aware tools, Gemini 3.5 Flash-Lite");   // every agent names its model
  assert.equal(categoryName("hard-silent"), "Silent");
  assert.equal(categoryName("new-kind"), "new-kind");
});

test("names: a built-in agent on another model names that model, not Gemini", () => {
  assert.equal(solverName("agent-v1@z-ai-glm-5.3-flash"), "V1 on z-ai-glm-5.3-flash");
  assert.equal(solverSub("agent-v1@z-ai-glm-5.3-flash"), "change-aware tools, another model");
  assert.equal(solverName("agent-v1-vague@m"), "V1 on m (vague alerts)");
  assert.equal(solverSub("my-agent@m"), "custom");   // not a built-in base
});

test("signed: true minus, and zero is +0.00", () => {
  assert.equal(signed(0.26), "+0.26");
  assert.equal(signed(-0.12), "−0.12");
  assert.equal(signed(-0.004), "+0.00");
});

test("pct, plural, num", () => {
  assert.equal(pct(0.594), "59%");
  assert.equal(plural(1, "run"), "1 run");
  assert.equal(plural(0, "run"), "0 runs");
  assert.equal(num(null), "");
  assert.equal(num(undefined), "");
  assert.equal(num(0), "0");
});

test("minutes: zero is a bare 0, others signed to a tenth", () => {
  assert.equal(minutes(0), "0");
  assert.equal(minutes(300), "+5 min");
  assert.equal(minutes(-90), "−1.5 min");
});

test("counted: most frequent first", () => {
  assert.equal(counted({ a: 1, b: 3 }), "b ×3, a ×1");
  assert.equal(counted(undefined), "");
});

test("mark: 1 hit, 0.5 part, 0 miss", () => {
  assert.equal(mark(1).cls, "hit");
  assert.deepEqual(mark(0.5), { cls: "part", glyph: "½", word: "partly correct" });
  assert.equal(mark(0).cls, "miss");
});

// ---------------------------------------------------------------- run strips

test("strip slots: planned runs, or more if more were recorded", () => {
  const data = { solvers: ["heuristic", "agent-v0"], planned_runs: { heuristic: 1, "agent-v0": 3 },
    incidents: [{ results: { heuristic: [1, 0], "agent-v0": [1] } }, { results: {} }] };
  assert.deepEqual(stripSlots(data), { heuristic: 2, "agent-v0": 3 });
  delete data.planned_runs;   // an older index.json
  assert.deepEqual(stripSlots(data), { heuristic: 2, "agent-v0": 1 });
});

test("strip: a tile per run, then empty tiles up to the slots", () => {
  const s = strip("agent-v0", [1, 0.5], 4);
  assert.deepEqual(s.tiles.map((m) => m && m.cls), ["hit", "part", null, null]);
  assert.equal(s.label, "V0 on Gemini: 1 of 2 runs correct, 1 partly correct, 2 not run yet");
  assert.equal(strip("agent-v0", [], 3).label, "V0 on Gemini: no runs recorded yet");
  assert.deepEqual(strip("agent-v0", [], 3).tiles, [null, null, null]);
});

// ---------------------------------------------------------------- headline

const row = (accuracy_mean, scenarios, expected = 16) => ({ accuracy_mean, scenarios, expected });
const incidents = (counts) => counts.map((c) => ({ results: c }));

test("headline: every batch complete, no partial note", () => {
  const data = { solvers: ["heuristic", "agent-v0"], planned_runs: { heuristic: 1, "agent-v0": 2 },
    incidents: incidents([{ heuristic: [1], "agent-v0": [1, 0] }, { heuristic: [0], "agent-v0": [1, 1] }]) };
  assert.deepEqual(answerText(data, { heuristic: row(0.59, 16), "agent-v0": row(0.41, 16) }),
    { headline: "Accuracy on the 16 fault incidents: heuristic 59% and v0 on Gemini 41%.", partial: "",
      complete: ["heuristic", "agent-v0"] });
});

test("headline: lowercases the first letter only, so Nemotron keeps its capital", () => {
  const data = { solvers: ["agent-v1-nemotron"], incidents: [] };
  assert.equal(answerText(data, { "agent-v1-nemotron": row(0.5, 16) }).headline,
    "Accuracy on the 16 fault incidents: v1 on Nemotron 50%.");
});

test("headline: null when no solver has an overall row", () => {
  assert.equal(answerText({ solvers: ["heuristic"], incidents: [] }, { heuristic: undefined }), null);
});

test("partial batch: incidents missing", () => {
  const data = { solvers: ["heuristic", "agent-v1"], planned_runs: { heuristic: 1, "agent-v1": 1 },
    incidents: incidents([{ heuristic: [1], "agent-v1": [1] }, { heuristic: [1], "agent-v1": [0] }]) };
  const text = answerText(data, { heuristic: row(0.5, 16), "agent-v1": row(0.6, 12) });
  assert.equal(text.partial, "V1 on Gemini is a partial batch so far (12 of 16 incidents); its 60% is not comparable yet.");
  assert.equal(text.headline, "Accuracy on the 16 fault incidents: heuristic 50%.");   // a partial batch is left out
  assert.deepEqual(text.complete, ["heuristic"]);
});

test("headline: one stray run of a model is left out of the headline", () => {
  const data = { solvers: ["heuristic", "agent-v1@m"], planned_runs: { heuristic: 1, "agent-v1@m": 5 },
    incidents: incidents([{ heuristic: [1], "agent-v1@m": [1] }, { heuristic: [0] }]) };
  const text = answerText(data, { heuristic: row(0.5, 16), "agent-v1@m": row(1, 1) });
  assert.equal(text.headline, "Accuracy on the 16 fault incidents: heuristic 50%.");
  assert.equal(text.partial,
    "V1 on m is a partial batch so far (1 of 16 incidents, 0–1 of 5 planned runs per incident); its 100% is not comparable yet.");
});

test("partial batch: fewer runs than planned on some incidents", () => {
  const data = { solvers: ["agent-v1"], planned_runs: { "agent-v1": 3 },
    incidents: incidents([{ "agent-v1": [1, 1, 1] }, { "agent-v1": [1] }]) };
  assert.equal(answerText(data, { "agent-v1": row(0.9, 16) }).partial,
    "V1 on Gemini is a partial batch so far (1–3 of 3 planned runs per incident); its 90% is not comparable yet.");
  assert.equal(answerText(data, { "agent-v1": row(0.9, 16) }).headline, "No batch is complete yet.");
});

test("partial batch: both clauses, and an even shortfall shows one number", () => {
  const data = { solvers: ["agent-v1"], planned_runs: { "agent-v1": 3 },
    incidents: incidents([{ "agent-v1": [1, 1] }, { "agent-v1": [0, 1] }]) };
  assert.equal(answerText(data, { "agent-v1": row(0.7, 10) }).partial,
    "V1 on Gemini is a partial batch so far (10 of 16 incidents, 2 of 3 planned runs per incident); its 70% is not comparable yet.");
});

test("partial batch: planned_runs absent (an older index.json) counts only missing incidents", () => {
  const data = { solvers: ["agent-v1"], incidents: incidents([{ "agent-v1": [1, 1, 1] }, { "agent-v1": [1] }]) };
  assert.equal(answerText(data, { "agent-v1": row(0.9, 16) }).partial, "");
  assert.equal(answerText(data, { "agent-v1": row(0.9, 15) }).partial,
    "V1 on Gemini is a partial batch so far (15 of 16 incidents); its 90% is not comparable yet.");
});

test("partial batch: a control incident short of its planned runs counts", () => {
  const data = { solvers: ["agent-v1"], planned_runs: { "agent-v1": 2 },
    incidents: [{ category: "easy", results: { "agent-v1": [1, 1] } },
      { category: "control", results: { "agent-v1": [1] } }] };
  assert.equal(answerText(data, { "agent-v1": row(1, 16) }).partial,
    "V1 on Gemini is a partial batch so far (1–2 of 2 planned runs per incident); its 100% is not comparable yet.");
});

test("headline: n falls back to scenarios without expected", () => {
  const data = { solvers: ["heuristic"], incidents: [] };
  assert.equal(answerText(data, { heuristic: { accuracy_mean: 1, scenarios: 4 } }).headline,
    "Accuracy on the 4 fault incidents: heuristic 100%.");
});

// ---------------------------------------------------------------- paired result

const pair = (a, b, mean_diff, ci, with_controls = null) => ({ a, b, n: 16, mean_diff, ci, with_controls });

test("paired: no agent clearly better, the best quoted, and the model pair with the controls", () => {
  const data = { paired: [pair("agent-v1-nemotron", "heuristic", 0.08, [-0.05, 0.23]),
    pair("agent-v1", "heuristic", -0.18, [-0.40, 0.02]),
    pair("agent-v1-nemotron", "agent-v1", 0.26, [0.10, 0.44], { n: 20, mean_diff: 0.11, ci: [-0.09, 0.31] })] };
  assert.equal(pairedText(data, ["heuristic", "agent-v1", "agent-v1-nemotron"]),
    "No agent is clearly better than the heuristic: on the 16 fault incidents, no paired 95% interval against it lies " +
    "above 0 (the best is V1 on Nemotron at +0.08, 95% interval −0.05 to +0.23). The same agent on two models: V1 on " +
    "Nemotron vs V1 on Gemini +0.26 (95% interval +0.10 to +0.44) on the fault incidents, and +0.11 (95% interval " +
    "−0.09 to +0.31) with the controls counted, where false alarms count too.");
});

test("paired: an interval wholly above or below 0 is called clearly better or worse; partial solvers are left out", () => {
  const data = { paired: [pair("agent-v0", "heuristic", 0.3, [0.1, 0.5]), pair("agent-v1", "heuristic", -0.3, [-0.5, -0.1]),
    pair("agent-v1-vague", "heuristic", 0.9, [0.8, 1.0])] };
  assert.equal(pairedText(data, ["heuristic", "agent-v0", "agent-v1"]),
    "V0 on Gemini is clearly better than the heuristic on the 16 fault incidents: V0 on Gemini +0.30 (95% interval " +
    "+0.10 to +0.50). V1 on Gemini is clearly worse than it.");
  assert.equal(pairedText({ paired: [pair("agent-v0", "heuristic", 0.3, null)] }, ["heuristic", "agent-v0"]), null);
  assert.equal(pairedText({}, ["heuristic"]), null);   // an older index.json without paired rows
});

// ---------------------------------------------------------------- incident alert

test("alert: a vague-alert solver sees its own alert, and the caption names who saw another one", () => {
  const data = { alert: "Checkout fails.", alerts_shown: { "agent-v1-nemotron-vague": "Something is wrong." } };
  assert.deepEqual(alertFor(data, "agent-v1-nemotron-vague"), { alert: "Something is wrong.",
    caption: "The generic alert V1 on Nemotron (vague alerts) was given instead of this incident’s. The other solvers saw: “Checkout fails.”" });
  assert.deepEqual(alertFor(data, "heuristic"), { alert: "Checkout fails.",
    caption: "The alert given to every solver except V1 on Nemotron (vague alerts), which was given a generic one." });
  assert.equal(alertFor({ alert: "Checkout fails." }, "heuristic").caption, "The alert every solver was given.");
});

// ---------------------------------------------------------------- sparkline

const series = (...ts) => ({ signal: "cpu", service: "cart", points: ts.map((t, i) => [t, i]) });

test("sparkline: the domain runs to window_end_s, and a series that stops early says so", () => {
  const g = sparkGeometry(series(-300, -60, 60), 300);
  assert.equal(g.t0, -300);
  assert.equal(g.t1, 300);
  assert.equal(g.stopped, "No points after +1 min.");
  assert.match(g.label, /^cpu for cart, one point per minute from −5 min to \+5 min around the alert; lowest 0, highest 2\. No points after \+1 min\.$/);
  assert.equal(g.at, 150);   // the alert is halfway along
  assert.equal(g.alertLeft, "50.0%");
  assert.equal(g.points, "0.0,44.0 120.0,24.0 180.0,4.0");
  assert.ok(g.after && g.alert);
});

test("sparkline: a series that ends one minute short of window_end_s is not a stop", () => {
  const g = sparkGeometry(series(-300, 0, 60), 120);
  assert.equal(g.t1, 120);
  assert.equal(g.stopped, null);
});

test("sparkline: a series past window_end_s keeps its own end", () => {
  assert.equal(sparkGeometry(series(-300, 0, 600), 300).t1, 600);
});

test("sparkline: a flat series sits mid-height; fewer than two finite points is null", () => {
  const g = sparkGeometry({ points: [[0, 5], [60, 5]] }, 60);
  assert.equal(g.points, "0.0,24.0 300.0,24.0");
  assert.equal(sparkGeometry({ points: [[0, 1], [60, null]] }, 300), null);
  assert.equal(sparkGeometry({}, 300), null);
});

// ---------------------------------------------------------------- trimmed outputs

test("trim notes: cut by the tool", () => {
  assert.deepEqual(trimNotes({ _cut_by_tool: true, samples: [] }),
    { tool: "The tool cut this output for the agent too, so the agent saw only part of it.", site: null });
});

test("trim notes: trimmed by the site, samples keep the last, other lists the first", () => {
  const o = { samples: [1, 2], spans: [1], _trimmed: { samples: 40, spans: 9 } };
  assert.deepEqual(trimNotes(o), { tool: null,
    site: "Shortened for the site: the last 2 of 40 samples, the first 1 of 9 spans are shown; the agent saw them all." });
  assert.equal(trimNotes({ ...o, _cut_by_tool: true }).site,
    "Shortened for the site: the last 2 of 40 samples, the first 1 of 9 spans are shown.");
  assert.deepEqual(trimNotes({}), { tool: null, site: null });
});

test("logs line: all, the last few, or cut by the tool", () => {
  assert.equal(logsLine({ total: 1, samples: [{}] }), "1 line matched.");
  assert.equal(logsLine({ total: 50, samples: [{}, {}] }), "50 lines matched; the tool returned the last 2.");
  assert.equal(logsLine({ total: 50, samples: [{}], _trimmed: { samples: 20 } }), "50 lines matched; the tool returned the last 20.");
  assert.equal(logsLine({ total: 50, samples: [{}], _cut_by_tool: true, _trimmed: { samples: 20 } }),
    "50 lines matched; the agent saw the oldest 20 of the lines returned before the tool cut its output.");
});

// ---------------------------------------------------------------- arguments and evidence

test("argText: key=value pairs, strings bare", () => {
  assert.equal(argText({ service: "cart", until: 120, tags: ["a"] }), 'service=cart  until=120  tags=["a"]');
  assert.equal(argText(null), "");
  assert.equal(argText("raw"), "raw");
  assert.equal(argText([1]), "1");
});

test("evidenceText: each kind, and anything else as JSON", () => {
  assert.equal(evidenceText("plain"), "plain");
  assert.equal(evidenceText({ kind: "metric", service: "cart", signal: "cpu", claim: "rose" }), "cart cpu: rose");
  assert.equal(evidenceText({ kind: "trace", trace_id: "ab12", service: "cart", claim: "slow" }), "Trace ab12 (cart): slow");
  assert.equal(evidenceText({ kind: "trace", claim: "slow" }), "Trace : slow");
  assert.equal(evidenceText({ kind: "log", service: "cart", quote: "boom" }), "cart log: “boom”");
  assert.equal(evidenceText({ kind: "text", text: 7 }), "7");
  assert.equal(evidenceText({ kind: "other" }), '{"kind":"other"}');
  assert.equal(evidenceText(3), "3");
});

// RootCause replay site: the pure logic behind the pages (names, marks, sentences, sparkline geometry), with no DOM.
// app.js builds the elements from what these return; site/tests/lib.test.mjs runs them under node --test.

export const CATEGORIES = {
  easy: ["Easy", "one loud fault"],
  "hard-cross-service": ["Cross-service", "the symptom shows up in a different service from the cause"],
  "hard-silent": ["Silent", "latency or resource faults with no errors"],
  "hard-noisy": ["Noisy", "a real fault plus a decoy traffic flood"],
  "hard-two-faults": ["Two-fault", "both causes must be named"],
  control: ["Control", "nothing is broken; the right answer is “no incident”"],
};

export const SOLVERS = {
  heuristic: ["Heuristic", "the simple rule"],
  "agent-v0": ["Agent v0", "naive tools"],
  "agent-v1": ["Agent v1", "change-aware tools"],
  "agent-v1-nopriors": ["V1 without priors", "ablation of agent v1"],
  "agent-v1-vague": ["V1 with vague alerts", "ablation of agent v1"],
  "agent-v0-nemotron": ["V0 on Nemotron", "naive tools, another model"],
  "agent-v1-nemotron": ["V1 on Nemotron", "agent v1, another model"],
  "agent-v1-nemotron-nopriors": ["V1 on Nemotron (no priors)", "ablation: two prompt sentences removed"],
  "agent-v1-nemotron-vague": ["V1 on Nemotron (vague alerts)", "ablation: one generic alert"],
  "agent-v1-nemotron-steps30": ["V1 on Nemotron (30 steps)", "ablation: twice the step limit"],
};

// a solver missing from SOLVERS (your own agent, or a built-in one on another model) shows its record name
export const solverName = (s) => (SOLVERS[s] || [s])[0];
export const solverSub = (s) => (SOLVERS[s] || [s, "custom"])[1];
export const categoryName = (c) => (CATEGORIES[c] || [c])[0];
export const pct = (x) => `${Math.round(x * 100)}%`;
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
export const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
export const num = (x) => (x === null || x === undefined ? "" : String(x));   // tool values already carry 4 significant digits
export const minutes = (t) => (t === 0 ? "0" : `${t < 0 ? "−" : "+"}${Math.round(Math.abs(t) / 6) / 10} min`);
export const counted = (obj) => Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ×${n}`).join(", ");
export const isTrueCause = (service, truth) => truth.some((c) => c.accept.includes(service));

/** A run's score as a mark: 1 is correct, 0 wrong, anything between partly correct (two-fault, one cause of two). */
export function mark(correct) {
  if (correct >= 1) return { cls: "hit", glyph: "✓", word: "correct" };
  if (correct > 0) return { cls: "part", glyph: "½", word: "partly correct" };
  return { cls: "miss", glyph: "✗", word: "wrong" };
}

// ---------------------------------------------------------------- index page

/** Run-strip slots per solver: the planned runs per incident (site.py), or more if more were recorded. */
export function stripSlots(data) {
  return Object.fromEntries(data.solvers.map((s) =>
    [s, Math.max(data.planned_runs?.[s] ?? 0, ...data.incidents.map((i) => (i.results[s] || []).length))]));
}

/** One incident's runs for one solver: its label, and a mark per tile with null for each slot not run yet. */
export function strip(solver, results, slots) {
  const name = solverName(solver);
  const counts = { hit: 0, part: 0, miss: 0 };
  results.forEach((c) => counts[mark(c).cls]++);
  const missing = slots - results.length;
  const label = !results.length
    ? `${name}: no runs recorded yet`
    : `${name}: ${counts.hit} of ${plural(results.length, "run")} correct` +
      (counts.part ? `, ${counts.part} partly correct` : "") +
      (missing ? `, ${missing} not run yet` : "");
  return { label, tiles: [...results.map(mark), ...Array(Math.max(0, missing)).fill(null)] };
}

/** {headline: "Accuracy on the 16 fault incidents: heuristic 59% and agent v0 41%.", partial: "..."}, with a note in
 * partial for each partial batch: one with fewer than its planned runs on some incident, or with incidents missing.
 * null when no solver has an overall row. */
export function answerText(data, overall) {
  const shown = data.solvers.filter((s) => overall[s]);
  if (!shown.length) return null;
  const n = overall[shown[0]].expected ?? overall[shown[0]].scenarios;
  const planned = data.planned_runs || {};   // absent in an older index.json: then only missing incidents count as partial
  const lowerFirst = (s) => s[0].toLowerCase() + s.slice(1);   // "V1 on Nemotron" -> "v1 on Nemotron"
  const parts = shown.map((s) => `${lowerFirst(solverName(s))} ${pct(overall[s].accuracy_mean)}`);
  const list = new Intl.ListFormat("en", { type: "conjunction" }).format(parts);
  const counts = (s) => data.incidents.map((i) => (i.results[s] || []).length);   // controls included
  const short = (s) => planned[s] && Math.min(...counts(s)) < planned[s];
  const partial = shown.filter((s) => short(s) || overall[s].scenarios < n).map((s) => {
    const lo = Math.min(...counts(s)), hi = Math.max(...counts(s));
    const clauses = [];
    if (overall[s].scenarios < n) clauses.push(`${overall[s].scenarios} of ${n} incidents`);
    if (short(s)) clauses.push(`${lo === hi ? lo : `${lo}–${hi}`} of ${plural(planned[s], "planned run")} per incident`);
    return `${solverName(s)} is a partial batch so far (${clauses.join(", ")}).`;
  });
  return { headline: `Accuracy on the ${n} fault incidents: ${list}.`, partial: partial.join(" ") };
}

// ---------------------------------------------------------------- incident page

/** get_metric's sparkline in a W x H box, or null with fewer than two finite points. The axis runs to the end of what
 * was asked for (args.until, capped at windowEndS, the seconds from the alert to the snapshot's end), so a series that
 * stops early (a paused service) visibly stops. */
export function sparkGeometry(o, args, windowEndS) {
  const pts = (o.points || []).filter((p) => Number.isFinite(p?.[0]) && Number.isFinite(p?.[1]));
  if (pts.length < 2) return null;
  const W = 300, H = 48, PAD = 4;
  const ts = pts.map((p) => p[0]), vs = pts.map((p) => p[1]);
  const last = Math.max(...ts), lo = Math.min(...vs), hi = Math.max(...vs);
  const asked = Number.isFinite(args.until) ? Math.min(args.until, windowEndS) : windowEndS;
  const t0 = Math.min(...ts), t1 = Math.max(last, asked);
  const stopped = t1 - last >= 120 ? `No points after ${minutes(last)}.` : null;
  const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const y = (v) => (hi === lo ? H / 2 : PAD + (1 - (v - lo) / (hi - lo)) * (H - 2 * PAD));
  const at = Math.min(W, Math.max(0, x(0)));
  const label = `${o.signal} for ${o.service}, one point per minute from ${minutes(t0)} to ${minutes(t1)} around the alert; ` +
    `lowest ${num(lo)}, highest ${num(hi)}${stopped ? `. ${stopped}` : ""}`;
  return { W, H, t0, t1, lo, hi, at, stopped, label,
    after: t1 >= 0,                 // the tinted stretch after the alert is in view
    alert: t0 <= 0 && t1 >= 0,      // the alert itself is in view
    points: pts.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" "),
    alertLeft: `${((at / W) * 100).toFixed(1)}%` };
}

/** search_logs' summary line: how many lines matched and which of them the samples are. */
export function logsLine(o) {
  return `${plural(o.total, "line")} matched` + (o._cut_by_tool
    ? `; the agent saw the oldest ${o._trimmed?.samples ?? o.samples.length} of the lines returned before the tool cut its output.`
    : (o._trimmed?.samples ?? o.samples.length) < o.total ? `; the tool returned the last ${o._trimmed?.samples ?? o.samples.length}.` : ".");
}

/** The notes under a tool output cut by the tool (_cut_by_tool) or shortened for the site (_trimmed): {tool, site}, each
 * a sentence or null. Log samples keep their newest lines (site._shrink), other lists their first. */
export function trimNotes(o) {
  const cut = Object.entries(o._trimmed || {})
    .map(([k, n]) => `the ${k === "samples" ? "last" : "first"} ${o[k]?.length ?? 0} of ${n} ${k}`).join(", ");
  return {
    tool: o._cut_by_tool ? "The tool cut this output for the agent too, so the agent saw only part of it." : null,
    site: cut ? `Shortened for the site: ${cut} are shown${o._cut_by_tool ? "" : "; the agent saw them all"}.` : null,
  };
}

export function argText(args) {
  if (!isObj(args)) return String(args ?? "");
  return Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("  ");
}

export function evidenceText(item) {
  if (typeof item === "string") return item;
  if (!isObj(item)) return JSON.stringify(item);
  const who = [item.service, item.signal].filter(Boolean).join(" ");
  if (item.kind === "metric") return `${who}: ${item.claim ?? ""}`;
  if (item.kind === "trace") return `Trace ${item.trace_id ?? ""}${who ? ` (${who})` : ""}: ${item.claim ?? ""}`;
  if (item.kind === "log") return `${who} log: “${item.quote ?? ""}”`;
  if (item.kind === "text") return String(item.text ?? "");
  return JSON.stringify(item);
}

// RootCause replay site: one ES module for every page. <body data-page="..."> picks the renderer (see the bottom).
// Shared helpers come first; each page's renderer follows.

const CATEGORIES = {
  easy: ["Easy", "one loud fault"],
  "hard-cross-service": ["Cross-service", "the symptom shows up in a different service from the cause"],
  "hard-silent": ["Silent", "latency or resource faults with no errors"],
  "hard-noisy": ["Noisy", "a real fault plus a decoy traffic flood"],
  "hard-two-faults": ["Two-fault", "both causes must be named"],
  control: ["Control", "nothing is broken; the right answer is “no incident”"],
};

const SOLVERS = {
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
const solverName = (s) => (SOLVERS[s] || [s])[0];
const solverSub = (s) => (SOLVERS[s] || [s, "custom"])[1];
const categoryName = (c) => (CATEGORIES[c] || [c])[0];
const pct = (x) => `${Math.round(x * 100)}%`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** h("a", {href, class}, ...children): build an element; strings become text nodes, so data is never parsed as HTML. */
function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return node;
}

/** Fetch JSON relative to the page; null when it is missing. Malformed JSON throws, so the page says to rebuild it. */
async function loadJSON(path) {
  let res;
  try {
    res = await fetch(path);
  } catch {
    return null;
  }
  return res.ok ? res.json() : null;
}

/** A run's score as a mark: 1 is correct, 0 wrong, anything between partly correct (two-fault, one cause of two). */
function mark(correct) {
  if (correct >= 1) return { cls: "hit", glyph: "✓", word: "correct" };
  if (correct > 0) return { cls: "part", glyph: "½", word: "partly correct" };
  return { cls: "miss", glyph: "✗", word: "wrong" };
}

const command = (text) => h("code", {}, text);

// ---------------------------------------------------------------- index page

function runStrip(solver, results, slots) {
  const name = solverName(solver);
  const counts = { hit: 0, part: 0, miss: 0 };
  results.forEach((c) => counts[mark(c).cls]++);
  const missing = slots - results.length;
  const label = !results.length
    ? `${name}: no runs recorded yet`
    : `${name}: ${counts.hit} of ${plural(results.length, "run")} correct` +
      (counts.part ? `, ${counts.part} partly correct` : "") +
      (missing ? `, ${missing} not run yet` : "");
  const tiles = results.map((c) => {
    const m = mark(c);
    return h("span", { class: `tile ${m.cls}` }, m.glyph);
  });
  for (let i = 0; i < missing; i++) tiles.push(h("span", { class: "tile empty" }));
  return h("span", { class: "strip", role: "img", "aria-label": label }, tiles);
}

function truthCell(truth) {
  if (!truth.length) return h("td", { class: "truth" }, h("span", { class: "none" }, "no fault"));
  return h("td", { class: "truth" },
    truth.map((c) => h("span", { class: "cause" },
      h("span", { class: "svc" }, c.accept.join(" or ")), " ", h("span", { class: "ftype" }, c.fault_type))));
}

function accuracyCell(row) {
  if (!row) return h("td", { class: "num" }, h("span", { class: "acc-none" }, "not run"));
  const lo = row.records_min, hi = row.records_max;
  const runs = lo === hi ? plural(lo, "run") : `${lo}–${hi} runs`;
  const spread = row.accuracy_std === null ? null : `± ${Math.round(row.accuracy_std * 100)} pts, `;
  const missing = row.expected && row.scenarios < row.expected ? `${row.scenarios} of ${row.expected} incidents, ` : null;
  return h("td", { class: "num" },
    h("span", { class: "acc" }, pct(row.accuracy_mean)),
    h("span", { class: "acc-detail" }, missing, spread, `${runs} each`));
}

function legend() {
  const item = (cls, glyph, text) => h("li", {}, h("span", { class: `tile ${cls}`, "aria-hidden": "true" }, glyph), text);
  return h("ul", { class: "legend", "aria-label": "Key" },
    item("hit", "✓", "correct"), item("miss", "✗", "wrong"),
    item("part", "½", "partly correct (one of two causes)"), item("empty", "", "not run yet"));
}

/** "Accuracy on the 16 fault incidents: heuristic 59% and agent v0 41%." plus a note for each partial batch: one with
 * fewer than its planned runs on some incident, or with incidents missing. */
function answer(data, overall) {
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
  return h("p", { class: "answer" }, `Accuracy on the ${n} fault incidents: ${list}. `, partial.join(" "));
}

async function renderIndex() {
  const root = document.getElementById("scoreboard");
  const data = await loadJSON("data/index.json");
  if (!data || !data.solvers?.length) {
    root.replaceChildren(h("p", { class: "status" },
      "No results yet. Run ", command("python -m rootcause site"), " to generate them."));
    return;
  }
  const solvers = data.solvers;
  // run-strip slots: the planned runs per incident (site.py), or more if more were recorded
  const slots = Object.fromEntries(solvers.map((s) =>
    [s, Math.max(data.planned_runs?.[s] ?? 0, ...data.incidents.map((i) => (i.results[s] || []).length))]));
  const summary = Object.fromEntries(solvers.map((s) =>
    [s, Object.fromEntries((data.summary[s] || []).map((r) => [r.category, r]))]));
  const width = solvers.length + 2;

  const head = h("thead", {}, h("tr", {},
    h("th", { scope: "col", class: "incident" }, "Incident"),
    h("th", { scope: "col" }, "True cause"),
    solvers.map((s) => h("th", { scope: "col", class: "solver" },
      solverName(s), h("span", { class: "sub" }, solverSub(s))))));

  const categories = [...data.categories, ...new Set(data.incidents.map((i) => i.category))]
    .filter((c, i, all) => all.indexOf(c) === i);
  const groups = categories.map((cat) => {
    const rows = data.incidents.filter((i) => i.category === cat);
    if (!rows.length) return null;
    return h("tbody", {},
      h("tr", { class: "group" }, h("th", { scope: "rowgroup", colspan: width },
        h("span", { class: "group-label" }, categoryName(cat),
          CATEGORIES[cat] ? h("span", { class: "sub" }, CATEGORIES[cat][1]) : null))),
      rows.map((inc) => h("tr", { class: "incident-row" },
        h("th", { scope: "row", class: "incident" },
          h("a", { href: `incident.html?id=${encodeURIComponent(inc.id)}` }, inc.id),
          inc.heldout ? h("span", { class: "heldout" }, "held out") : null,
          h("span", { class: "alert" }, inc.alert)),
        truthCell(inc.truth),
        solvers.map((s) => h("td", { class: "runs" }, runStrip(s, inc.results[s] || [], slots[s]))))),
      h("tr", { class: "acc-row" },
        h("th", { scope: "row", class: "incident" }, `${categoryName(cat)} accuracy`),
        h("td", {}),
        solvers.map((s) => accuracyCell(summary[s][cat]))));
  });

  const overall = Object.fromEntries(solvers.map((s) => [s, summary[s]["all incidents"]]));
  const anyOverall = solvers.some((s) => overall[s]);
  const foot = anyOverall ? h("tfoot", {}, h("tr", { class: "acc-row total" },
    h("th", { scope: "row", class: "incident" }, "All fault incidents"),
    h("td", {}),
    solvers.map((s) => accuracyCell(overall[s])))) : null;

  const table = h("table", { class: solvers.length > 4 ? "scoreboard dense" : "scoreboard" },
    h("caption", { class: "visually-hidden" },
      "Scoreboard: one mark per recorded run, for each incident and solver, with accuracy by category"),
    head, groups, foot);

  root.replaceChildren(
    answer(data, overall) || "",
    legend(),
    h("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Scoreboard" }, table));
  document.getElementById("generated").replaceChildren(
    `Results generated ${data.generated} from the run records with `, command("python -m rootcause site"), ".");
}

/** A figure whose PNG is missing says how to make it instead of showing a broken image. */
function guardFigures() {
  for (const img of document.querySelectorAll(".figures img")) {
    const missing = () => img.replaceWith(h("p", { class: "status" }, "This chart has not been generated yet. Run ",
      command("python -m rootcause report"), ", then ", command("python -m rootcause site"), "."));
    if (img.complete && !img.naturalWidth) missing();
    else img.addEventListener("error", missing, { once: true });
  }
}

// ---------------------------------------------------------------- incident page

/** svgEl("line", {x1, ...}): h() for SVG, which needs createElementNS. Only attributes and child nodes, never markup. */
function svgEl(tag, attrs = {}, ...kids) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  node.append(...kids.filter(Boolean));
  return node;
}

const isObj = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
const num = (x) => (x === null || x === undefined ? "" : String(x));   // tool values already carry 4 significant digits
const minutes = (t) => (t === 0 ? "0" : `${t < 0 ? "−" : "+"}${Math.round(Math.abs(t) / 6) / 10} min`);
const fact = (term, ...detail) => h("div", {}, h("dt", {}, term), h("dd", {}, ...detail));
const counted = (obj) => Object.entries(obj || {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ×${n}`).join(", ");
const isTrueCause = (service, truth) => truth.some((c) => c.accept.includes(service));

/** A table inside its own sideways-scrolling region, so a wide tool output never widens the page. */
function dataTable(label, cols, rows) {
  return h("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": label },
    h("table", { class: "out" },
      h("thead", {}, h("tr", {}, cols.map(([c, isNum]) => h("th", { scope: "col", class: isNum ? "num" : null }, c)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, r.map((v, i) => h("td", { class: cols[i][1] ? "num" : null }, v)))))));
}

const errorCell = (isError) => (isError ? h("span", { class: "bad" }, "✗ error") : "");
const note = (text) => (text ? h("p", { class: "note" }, text) : null);

function changesTable(rows, label, text) {
  if (!rows.length) return [h("p", { class: "out-line" }, "No changes."), note(text)];
  return [dataTable(label, [["Service"], ["Signal"], ["Before", 1], ["After", 1], ["Change", 1]],
    rows.map((r) => [r.service, r.signal, num(r.before), num(r.after), r.change])), note(text)];
}

/** get_metric as a sparkline: the alert (t=0) is a vertical rule and everything after it is tinted. */
let windowEndS = 300;  // seconds from the alert to the snapshot's end: the incident JSON's window_end_s (config.SETTLE_S)

function sparkline(o, args = {}) {
  const pts = (o.points || []).filter((p) => Number.isFinite(p?.[0]) && Number.isFinite(p?.[1]));
  if (pts.length < 2) return rawOutput({ output: o, truncated: false });
  const W = 300, H = 48, PAD = 4;
  const ts = pts.map((p) => p[0]), vs = pts.map((p) => p[1]);
  const last = Math.max(...ts), lo = Math.min(...vs), hi = Math.max(...vs);
  // the axis runs to the end of what was asked for, so a series that stops early (a paused service) visibly stops
  const asked = Number.isFinite(args.until) ? Math.min(args.until, windowEndS) : windowEndS;
  const t0 = Math.min(...ts), t1 = Math.max(last, asked);
  const stopped = t1 - last >= 120 ? `No points after ${minutes(last)}.` : null;
  const x = (t) => ((t - t0) / (t1 - t0 || 1)) * W;
  const y = (v) => (hi === lo ? H / 2 : PAD + (1 - (v - lo) / (hi - lo)) * (H - 2 * PAD));
  const at = Math.min(W, Math.max(0, x(0)));
  const label = `${o.signal} for ${o.service}, one point per minute from ${minutes(t0)} to ${minutes(t1)} around the alert; ` +
    `lowest ${num(lo)}, highest ${num(hi)}${stopped ? `. ${stopped}` : ""}`;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "spark", role: "img", "aria-label": label },
    t1 >= 0 ? svgEl("rect", { x: at, y: 0, width: W - at, height: H, class: "spark-after" }) : null,
    t0 <= 0 && t1 >= 0 ? svgEl("line", { x1: at, x2: at, y1: 0, y2: H, class: "spark-alert", "vector-effect": "non-scaling-stroke" }) : null,
    svgEl("polyline", { points: pts.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" "),
      class: "spark-line", "vector-effect": "non-scaling-stroke" }));
  return h("figure", { class: "spark-fig" },
    svg,
    h("div", { class: "spark-range", "aria-hidden": "true" }, h("span", {}, `max ${num(hi)}`), h("span", {}, `min ${num(lo)}`)),
    h("figcaption", { class: "spark-axis" },
      h("span", {}, minutes(t0)),
      t0 <= 0 && t1 >= 0 ? h("span", { class: "spark-zero", style: `left: ${((at / W) * 100).toFixed(1)}%` }, "alert") : null,
      h("span", {}, minutes(t1))),
    stopped ? note(stopped) : null);
}

/** One renderer per tool, written against the shapes in rootcause/tools_v0.py and tools_v1.py. */
const RENDER = {
  list_services: (o) => h("p", { class: "out-line" }, `${plural(o.services.length, "service")}: ${o.services.join(", ")}.`),
  get_metric: sparkline,
  search_traces: (o) => [
    h("dl", { class: "facts" },
      fact("Spans found", num(o.spans_found)), fact("Errors", num(o.errors)),
      Object.keys(o.operations || {}).length ? fact("Operations", counted(o.operations)) : null,
      Object.keys(o.error_messages || {}).length ? fact("Error messages", counted(o.error_messages)) : null),
    o.slowest?.length ? dataTable(`Slowest ${o.service} spans`,
      [["t (s)", 1], ["Duration (ms)", 1], ["Operation"], ["Error"], ["Trace"]],
      o.slowest.map((s) => [num(s.t), num(s.dur_ms), s.name, errorCell(s.error), h("code", {}, String(s.trace_id).slice(0, 8))])) : null],
  get_trace: (o) => dataTable(`Spans of trace ${String(o.trace_id).slice(0, 8)}`,
    [["t (s)", 1], ["Service"], ["Operation"], ["Duration (ms)", 1], ["Error"]],
    o.spans.map((s) => [num(s.t), s.service, [s.name, s.message ? h("span", { class: "msg" }, s.message) : null],
      num(s.dur_ms), errorCell(s.error)])),
  search_logs: (o) => [
    h("p", { class: "out-line" }, `${plural(o.total, "line")} matched` + (o._cut_by_tool
      ? `; the agent saw the oldest ${o._trimmed?.samples ?? o.samples.length} of the lines returned before the tool cut its output.`
      : (o._trimmed?.samples ?? o.samples.length) < o.total ? `; the tool returned the last ${o._trimmed?.samples ?? o.samples.length}.` : ".")),
    o.samples.length ? h("pre", { class: "out-pre", tabindex: "0" },
      o.samples.map((l) => `t=${l.t}  ${l.severity ?? "no severity"}  ${l.body}`).join("\n")) : null],
  top_changes: (o) => changesTable(o.changes, "Largest changes", o.note),
  service_health: (o) => changesTable(o.signals, `Health of ${o.service}`),
  service_map: (o) => [!o.edges.length ? h("p", { class: "out-line" }, "No calls between services.") : dataTable("Service map",
    [["Caller"], ["Callee"], ["Calls before", 1], ["Calls after", 1], ["Errors before", 1], ["Errors after", 1]],
    o.edges.map((e) => [e.caller, e.stopped ? [e.callee, " ", h("span", { class: "bad stopped" }, "✗ stopped")] : e.callee,
      num(e.calls_before), num(e.calls_after), num(e.errors_before), num(e.errors_after)])), note(o.note)],
};

/** Errors, truncated text, unknown tools and unexpected shapes: the output as text, never parsed as markup. */
function rawOutput(step) {
  const o = step.output;
  return [
    isObj(o) && "error" in o ? h("p", { class: "out-line bad" }, "✗ The tool returned an error.") : null,
    h("pre", { class: "out-pre", tabindex: "0" }, typeof o === "string" ? o : JSON.stringify(o)),
    step.truncated ? note("Truncated: the site keeps the first 3,000 characters of each tool output.") : null];
}

function renderOutput(step) {
  const o = step.output;
  if (!isObj(o) || "error" in o || !RENDER[step.tool]) return rawOutput(step);
  const cut = Object.entries(o._trimmed || {})   // log samples keep their newest lines (site._shrink), other lists their first
    .map(([k, n]) => `the ${k === "samples" ? "last" : "first"} ${o[k]?.length ?? 0} of ${n} ${k}`).join(", ");
  try {
    return [RENDER[step.tool](o, isObj(step.args) ? step.args : {}),
      o._cut_by_tool ? note("The tool cut this output for the agent too, so the agent saw only part of it.") : null,
      cut ? note(`Shortened for the site: ${cut} are shown${o._cut_by_tool ? "" : "; the agent saw them all"}.`) : null];
  } catch {
    return rawOutput(step);   // a shape the renderer does not expect is still shown, as text
  }
}

function argText(args) {
  if (!isObj(args)) return String(args ?? "");
  return Object.entries(args).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("  ");
}

function stepItem(step) {
  const args = argText(step.args);
  return h("li", { class: "step" },
    h("p", { class: "call" }, h("span", { class: "tool" }, step.tool), args ? h("code", { class: "args" }, args) : null),
    h("div", { class: "output" }, renderOutput(step)));
}

function causeLine(c, truth) {
  const ok = isTrueCause(c.service, truth);
  return [h("span", { class: ok ? "svc" : "svc-other" }, c.service), " ", h("span", { class: "ftype" }, c.fault_type),
    ok ? h("span", { class: "good" }, " ✓ true cause") : null];
}

function answerOf(run, truth) {
  if (run.verdict === "no_incident") return h("p", { class: "said" }, "No incident");
  if (run.verdict !== "incident") return h("p", { class: "said" }, "Not enough evidence (no answer, which counts as wrong)");
  return h("ol", { class: "ranked" }, run.causes.map((c) => h("li", {}, causeLine(c, truth))));
}

function truthOf(truth) {
  if (!truth.length) return h("p", { class: "said" }, "Nothing is broken; the right answer is “no incident”.");
  return h("ul", { class: "truth-list" }, truth.map((c) =>
    h("li", {}, h("span", { class: "svc" }, c.accept.join(" or ")), " ", h("span", { class: "ftype" }, c.fault_type))));
}

function resultLine(run, size = "") {
  const m = mark(run.score?.correct ?? 0);
  return h("p", { class: `result ${m.cls} ${size}` }, h("span", { "aria-hidden": "true" }, `${m.glyph} `),
    m.word[0].toUpperCase() + m.word.slice(1));
}

function evidenceText(item) {
  if (typeof item === "string") return item;
  if (!isObj(item)) return JSON.stringify(item);
  const who = [item.service, item.signal].filter(Boolean).join(" ");
  if (item.kind === "metric") return `${who}: ${item.claim ?? ""}`;
  if (item.kind === "trace") return `Trace ${item.trace_id ?? ""}${who ? ` (${who})` : ""}: ${item.claim ?? ""}`;
  if (item.kind === "log") return `${who} log: “${item.quote ?? ""}”`;
  if (item.kind === "text") return String(item.text ?? "");
  return JSON.stringify(item);
}

function badges(e) {
  if (e.grounded === null && e.distinctive === null) return h("span", { class: "badge unchecked" }, "not checked");
  const one = (value, word) => (value === null ? h("span", { class: "badge unchecked" }, `${word} not checked`)
    : value ? h("span", { class: "badge good" }, `✓ ${word}`) : h("span", { class: "badge bad" }, `✗ not ${word}`));
  return [one(e.grounded, "grounded"), one(e.distinctive, "distinctive")];
}

function verdictPanel(data, solver, run) {
  const rule = solver === "heuristic" ? null : data.runs.heuristic?.[0];
  // focusable because on desktop it is a sticky panel that scrolls on its own when the evidence is long
  return h("aside", { class: "verdict", "aria-labelledby": "verdict-title", tabindex: "0" },
    h("h2", { id: "verdict-title" }, "Verdict"),
    resultLine(run, "big"),
    run.error ? h("p", { class: "problem" }, "This run failed: ", run.error) : null,
    run.parse_error ? h("p", { class: "problem" }, "The final answer could not be read, so it counts as no answer: ", run.parse_error) : null,
    h("dl", { class: "verdict-facts" },
      fact(`${solverName(solver)} answered`, answerOf(run, data.truth)),
      fact(data.truth.length > 1 ? "True causes" : "True cause", truthOf(data.truth)),
      fact("Confidence", run.confidence === null || run.confidence === undefined ? "not given" : pct(run.confidence))),
    solver === "heuristic" ? null : h("section", { class: "rule", "aria-labelledby": "rule-title" },
      h("h3", { id: "rule-title" }, "The simple rule, same incident"),
      rule ? [resultLine(rule), answerOf(rule, data.truth)] : h("p", {}, "The simple rule has no run for this incident.")),
    h("section", { class: "evidence", "aria-labelledby": "evidence-title" },
      h("h3", { id: "evidence-title" }, "Cited evidence"),
      run.evidence.length
        ? h("ul", { class: "evidence-list" }, run.evidence.map((e) =>
          h("li", {}, h("span", { class: "claim" }, evidenceText(e.item)), h("span", { class: "badges" }, badges(e)))))
        : h("p", {}, "No evidence was cited.")));
}

function investigation(solver, run) {
  const usage = run.requests === null || run.requests === undefined ? null
    : `${plural(run.requests, "model request")}, ${(run.prompt_tokens ?? 0).toLocaleString("en")} prompt tokens and ` +
      `${(run.completion_tokens ?? 0).toLocaleString("en")} completion tokens.`;
  return h("section", { class: "investigation", "aria-labelledby": "steps-title" },
    h("h2", { id: "steps-title" }, "Investigation"),
    run.steps.length
      ? [h("p", { class: "note" }, `${plural(run.steps.length, "tool call")}. `, usage),
        h("ol", { class: "timeline" }, run.steps.map(stepItem))]
      : h("p", {}, solver === "heuristic"
        ? "The simple rule does not investigate: it ranks every service by how much its fault signals rose, so there are no steps to replay."
        : "This run made no tool calls. ", solver === "heuristic" ? null : usage));
}

async function renderIncident() {
  const root = document.getElementById("incident");
  const query = new URLSearchParams(location.search);
  const id = query.get("id") || "";
  const data = /^[a-z0-9][a-z0-9-]*$/i.test(id) ? await loadJSON(`data/incidents/${id}.json`) : null;
  if (!data) {
    root.replaceChildren(h("p", { class: "status" }, id ? `No incident called ${id}. ` : "No incident was named. ",
      h("a", { href: "./" }, "Back to the scoreboard"), "."));
    return;
  }
  document.title = `${data.id}: RootCause replay`;
  windowEndS = data.window_end_s ?? 300;

  const runs = data.runs || {};
  const known = Object.keys(SOLVERS);
  const rank = (s) => (known.includes(s) ? known.indexOf(s) : known.length);
  const have = Object.keys(runs).filter((s) => runs[s]?.length).sort((a, b) => rank(a) - rank(b));
  const state = { solver: query.get("solver") || have.find((s) => s.startsWith("agent")) || have[0] || "",
    run: Number.parseInt(query.get("run"), 10) || 1 };
  const choices = have.includes(state.solver) || !state.solver ? have : [...have, state.solver];

  const solverPick = h("select", { id: "pick-solver" },
    choices.map((s) => h("option", { value: s, selected: s === state.solver }, solverName(s))));
  const runPick = h("select", { id: "pick-run" });
  const replayButton = h("button", { type: "button", class: "primary" }, "Replay");
  const showButton = h("button", { type: "button" }, "Show all");
  const status = h("p", { class: "replay-status", role: "status" });
  const body = h("div", { class: "replay-body" });
  const category = CATEGORIES[data.category];

  root.replaceChildren(
    h("header", { class: "incident-head" },
      h("h1", {}, data.id),
      h("p", { class: "incident-meta" },
        category ? `${category[0]}: ${category[1]}.` : `${categoryName(data.category)}.`,
        data.heldout ? h("span", { class: "heldout" }, "Held out from tuning (one exception is disclosed in the report).") : null),
      h("figure", { class: "alert-quote" },
        h("blockquote", {}, h("p", {}, data.alert)),
        h("figcaption", {}, "The alert every solver was given."))),
    h("div", { class: "controls" },
      h("div", { class: "pick" }, h("label", { for: "pick-solver" }, "Solver"), solverPick),
      h("div", { class: "pick" }, h("label", { for: "pick-run" }, "Run"), runPick),
      h("div", { class: "replay-buttons" }, replayButton, showButton),
      status),
    body);

  let timer = null;
  const stop = () => { clearTimeout(timer); timer = null; };
  const showAll = (message = "") => {
    stop();
    body.querySelectorAll(".pending").forEach((el) => el.classList.remove("pending"));
    status.textContent = message;
  };

  function replay() {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      showAll("Reduced motion is on, so every step is shown at once.");
      return;
    }
    stop();
    const items = [...body.querySelectorAll(".step"), body.querySelector(".verdict")];
    items.forEach((el) => el.classList.remove("revealed"));
    items.forEach((el) => el.classList.add("pending"));
    let i = 0;
    const next = () => {
      const el = items[i++];
      el.classList.remove("pending");
      el.classList.add("revealed");
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      const done = i === items.length;
      status.textContent = done ? "Replay finished. The verdict is shown." : `Step ${i} of ${items.length - 1}`;
      if (!done) timer = setTimeout(next, 600);
    };
    timer = setTimeout(next, 300);
  }

  function draw() {
    stop();
    status.textContent = "";
    const list = Object.hasOwn(runs, state.solver) ? runs[state.solver] : [];
    const run = list.find((r) => r.run + 1 === state.run) || list[0];
    runPick.replaceChildren(...(list.length
      ? list.map((r) => h("option", { value: r.run + 1, selected: r === run }, `Run ${r.run + 1}`))
      : [h("option", { value: "" }, "none")]));
    runPick.disabled = !list.length;
    if (!run) {
      replayButton.hidden = showButton.hidden = true;
      body.replaceChildren(h("p", { class: "status" }, "This solver has no recorded runs for this incident yet."));
      return;
    }
    state.run = run.run + 1;
    replayButton.hidden = showButton.hidden = !run.steps.length;
    body.replaceChildren(verdictPanel(data, state.solver, run), investigation(state.solver, run));
  }

  const syncURL = () => history.replaceState(null, "", `?${new URLSearchParams({ id: data.id, solver: state.solver, run: state.run })}`);
  const pick = () => {
    state.solver = solverPick.value;
    state.run = Number(runPick.value) || 1;
    draw();
    syncURL();
  };
  solverPick.addEventListener("change", pick);
  runPick.addEventListener("change", pick);
  replayButton.addEventListener("click", replay);
  showButton.addEventListener("click", () => showAll());
  const asked = state.run;
  draw();
  if (Object.hasOwn(runs, state.solver) && runs[state.solver].length) syncURL();
  if (query.has("run") && asked !== state.run) status.textContent = `Run ${query.get("run")} was not recorded, so run ${state.run} is shown.`;
}

// ---------------------------------------------------------------- dispatch

const pages = {
  index: () => { guardFigures(); return renderIndex(); },
  incident: renderIncident,
};
Promise.resolve(pages[document.body.dataset.page]?.()).catch((err) => {  // malformed data must not leave "Loading" up
  console.error(err);
  const root = document.querySelector("[data-root]") ?? document.querySelector("main");
  root.replaceChildren(h("p", { class: "status" }, "These results could not be read. Rebuild them with ",
    command("python -m rootcause site"), "."));
});

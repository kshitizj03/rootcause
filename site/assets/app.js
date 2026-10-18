// RootCause replay site: one ES module for every page. <body data-page="..."> picks the renderer (see the bottom).
// Shared helpers come first; each page's renderer follows. The pure logic (names, marks, sentences, geometry) is in lib.js.

import {
  CATEGORIES, SOLVERS, solverName, solverSub, categoryName, pct, signed, plural, isObj, num, minutes, counted, isTrueCause,
  mark, stripSlots, strip, answerText, alertFor, sparkGeometry, logsLine, trimNotes, argText, evidenceText,
  modelOf, toolsOf, isPartial, mainSolvers, vsRuleRows, findingRows, forestDomain, at,
} from "./lib.js";

const REPO = "https://github.com/kshitizj03/rootcause";
const REPORT = `${REPO}/blob/main/docs/results/report.md`;

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

const command = (text) => h("code", {}, text);

// ---------------------------------------------------------------- index page

function runStrip(solver, results, slots) {
  const { label, tiles } = strip(solver, results, slots);
  return h("span", { class: "strip", role: "img", "aria-label": label },
    tiles.map((m) => (m ? h("span", { class: `tile ${m.cls}` }, m.glyph) : h("span", { class: "tile empty" }))));
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
    item("part", "½", "partly correct (one of two causes)"), item("empty", "", "not run yet"),
    h("li", {}, h("span", { class: "heldout" }, "held out"), "not used while developing the agents (one disclosed exception)"));
}

/** A solver's chart mark: its model's colour, filled for change-aware tools (v1), hollow for naive ones (v0). */
const swatch = (s, extra = "") => h("span", { class: `dot m-${modelOf(s)} t-${toolsOf(s) ?? "rule"} ${extra}`, "aria-hidden": "true" });

/** Axis ticks every 0.1 under a forest plot, as signed accuracy points. */
function forestAxis(domain) {
  const ticks = [];
  for (let v = domain[0]; v <= domain[1] + 1e-9; v += 0.1) ticks.push(Math.round(v * 10) / 10);
  return h("div", { class: "f-axis", "aria-hidden": "true" },
    h("span", { class: "f-axis-pad" }),
    h("div", { class: "f-track" }, ticks.map((v) =>
      h("span", { class: v === 0 ? "f-tick zero" : "f-tick", style: `left:${at(v, domain)}` }, v === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`))));
}

/** One interval on a forest row: a bar from ci[0] to ci[1] and a dot at the mean, coloured by solver. */
function interval(s, mean, ci, domain, cls = "") {
  return h("span", { class: `f-int ${cls}` },
    h("span", { class: `f-bar m-${modelOf(s)}`, style: `left:${at(ci[0], domain)};right:calc(100% - ${at(ci[1], domain)})` }),
    h("span", { class: `dot m-${modelOf(s)} t-${toolsOf(s) ?? "rule"} f-dot`, style: `left:${at(mean, domain)}` }));
}

const diffText = (mean, ci) => `${signed(mean)} (95% interval ${signed(ci[0])} to ${signed(ci[1])})`;

/** The hero: each complete agent's accuracy minus the rule's, with its 95% interval, around a zero line. */
function vsRulePlot(data, rows, overall) {
  const domain = forestDomain(rows);
  const rule = overall.heuristic;
  return h("figure", { class: "forest hero-plot" },
    h("div", { class: "f-scale", "aria-hidden": "true" },
      h("span", { class: "f-axis-pad" }),
      h("div", { class: "f-ends" }, h("span", {}, "worse than the rule"), h("span", {}, "better than the rule"))),
    h("ul", { class: "f-rows", role: "list" }, rows.map((r) =>
      h("li", { class: "f-row" },
        h("span", { class: "f-label" }, swatch(r.s), h("span", { class: "f-name" }, solverName(r.s)),
          h("span", { class: "f-sub" }, `${pct(overall[r.s].accuracy_mean)} of ${r.n} fault incidents`)),
        h("div", { class: "f-track", role: "img", "aria-label": `${solverName(r.s)} minus the rule: ${diffText(r.mean, r.ci)}` },
          h("span", { class: "f-zero" }), interval(r.s, r.mean, r.ci, domain))))),
    forestAxis(domain),
    h("figcaption", {}, `Each agent’s accuracy minus the simple rule’s (${rule ? pct(rule.accuracy_mean) : "n/a"}) on the same `,
      `${rows[0]?.n ?? 16} fault incidents, with a 95% bootstrap interval over incidents. `,
      rows.every((r) => r.ci[0] <= 0) ? "Every interval crosses zero: none is clearly better." : "An interval wholly right of zero is clearly better."));
}

/** What moved accuracy: the paired comparisons that change one thing, fault-only and with the controls counted. */
function findingsPlot(rows) {
  const domain = forestDomain(rows);
  let group = null;
  const items = [];
  for (const r of rows) {
    if (r.group !== group) {
      group = r.group;
      items.push(h("li", { class: "f-group" }, { Model: "Change the model", Tools: "Change the tools", Ablation: "Change one input",
        Other: "Other comparisons" }[group]));
    }
    items.push(h("li", { class: "f-row" },
      h("span", { class: "f-label" }, swatch(r.s), h("span", { class: "f-name" }, r.change), h("span", { class: "f-sub" }, r.fixed)),
      h("div", { class: "f-track double", role: "img",
        "aria-label": `${r.change}, ${r.fixed}: ${diffText(r.mean, r.ci)} on the fault incidents` +
          (r.controls ? `; ${diffText(r.controls.mean, r.controls.ci)} with the controls counted` : "") },
      h("span", { class: "f-zero" }), interval(r.s, r.mean, r.ci, domain),
      r.controls ? interval(r.s, r.controls.mean, r.controls.ci, domain, "ctl") : null)));
  }
  return h("figure", { class: "forest" },
    h("ul", { class: "f-rows", role: "list" }, items),
    forestAxis(domain),
    h("figcaption", {},
      h("span", { class: "keys" },
        h("span", { class: "key" }, h("span", { class: "key-bar" }), "fault incidents only"),
        h("span", { class: "key" }, h("span", { class: "key-bar ctl" }), "with the 4 no-fault controls counted, so false alarms cost")),
      "Change in accuracy, with a 95% interval. About a dozen comparisons are shown without correction, so one that only just clears zero is suggestive."));
}

/** Accuracy by incident type: one row per category, a dot per main batch on a 0-100% track. */
function categoryPlot(data, solvers, summary) {
  const cats = [...data.categories, "all incidents"];
  const label = (c) => (c === "all incidents" ? "All fault incidents" : categoryName(c));
  const domain = [0, 1];
  return h("figure", { class: "dotplot" },
    h("ul", { class: "f-rows", role: "list" }, cats.map((c) => {
      const pts = solvers.filter((s) => summary[s][c]);
      return h("li", { class: c === "all incidents" ? "f-row total" : "f-row" },
        h("span", { class: "f-label" }, h("span", { class: "f-name" }, label(c)),
          CATEGORIES[c] ? h("span", { class: "f-sub" }, CATEGORIES[c][1]) : null),
        h("div", { class: "f-track", role: "img",
          "aria-label": `${label(c)}: ${pts.map((s) => `${solverName(s)} ${pct(summary[s][c].accuracy_mean)}`).join(", ")}` },
          [0.25, 0.5, 0.75].map((v) => h("span", { class: "f-grid", style: `left:${at(v, domain)}` })),
          pts.map((s, i) => h("span", { class: `dot m-${modelOf(s)} t-${toolsOf(s) ?? "rule"} f-dot lane-${i}`,
            style: `left:${at(summary[s][c].accuracy_mean, domain)}`, title: `${solverName(s)}: ${pct(summary[s][c].accuracy_mean)}` }))));
    })),
    h("div", { class: "f-axis", "aria-hidden": "true" }, h("span", { class: "f-axis-pad" }),
      h("div", { class: "f-track" }, [0, 0.25, 0.5, 0.75, 1].map((v) => h("span", { class: "f-tick", style: `left:${at(v, domain)}` }, pct(v))))),
    h("figcaption", {}, h("span", { class: "keys" }, solvers.map((s) => h("span", { class: "key" }, swatch(s), solverName(s)))),
      "Accuracy is the mean over incidents of each incident’s mean score across its runs; on controls it is the share answered “no incident”."));
}

/** Accuracy vs coverage as the confidence threshold rises, one line per main agent, as an SVG in theme colours. */
function coveragePlot(data, solvers) {
  const W = 560, H = 300, L = 44, R = 12, T = 12, B = 34;
  const x = (c) => L + c * (W - L - R), y = (a) => T + (1 - a) * (H - T - B);
  const agents = solvers.filter((s) => data.coverage?.[s]?.length && s !== "heuristic");
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "cov", role: "img",
    "aria-label": `Accuracy against coverage for ${agents.map(solverName).join(", ")}: answering fewer runs by raising the confidence threshold does not raise accuracy consistently.` },
    ...[0, 0.25, 0.5, 0.75, 1].flatMap((v) => [
      svgEl("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "cov-grid" }),
      svgEl("text", { x: L - 8, y: y(v) + 4, class: "cov-tick", "text-anchor": "end" }, document.createTextNode(pct(v))),
      svgEl("text", { x: x(v), y: H - 12, class: "cov-tick", "text-anchor": "middle" }, document.createTextNode(pct(v)))]),
    ...agents.flatMap((s) => {
      const pts = data.coverage[s].map((p) => [x(p.coverage), y(p.accuracy)]);
      return [svgEl("polyline", { points: pts.map((p) => p.join(",")).join(" "), class: `cov-line m-${modelOf(s)}` }),
        ...pts.map(([cx, cy]) => svgEl("circle", { cx, cy, r: 4, class: `cov-pt m-${modelOf(s)} t-${toolsOf(s)}` }))];
    }));
  return h("figure", { class: "coverage" }, svg,
    h("figcaption", {}, h("span", { class: "keys" }, agents.map((s) => h("span", { class: "key" }, swatch(s), solverName(s)))),
      "Across: the share of runs answered at or above a confidence threshold. Up: accuracy of those runs, counted per run over all 20 incidents. ",
      "If stated confidence meant something, the lines would rise to the left; they mostly do not."));
}

async function renderIndex() {
  const root = document.getElementById("scoreboard");
  const data = await loadJSON("data/index.json");
  if (!data) {
    root.replaceChildren(h("p", { class: "status" },
      "No results built yet. Run ", command("python -m rootcause site"), "."));
    return;
  }
  if (!data.solvers?.length) {
    root.replaceChildren(h("p", { class: "status" },
      "No run records yet. Results come from data/runs, which is not in the repository: get the data release with ",
      command("python -m rootcause fetch-data"), " (or record incidents and run solvers), then run ",
      command("python -m rootcause site"), "."));
    return;
  }
  const summary = Object.fromEntries(data.solvers.map((s) =>
    [s, Object.fromEntries((data.summary[s] || []).map((r) => [r.category, r]))]));
  const overall = Object.fromEntries(data.solvers.map((s) => [s, summary[s]["all incidents"]]));
  const main = mainSolvers(data, overall);
  const complete = data.solvers.filter((s) => overall[s] && !isPartial(data, s, overall));

  const rows = vsRuleRows(data, main);
  if (rows.length) {
    const yes = rows.some((r) => r.ci[0] > 0);
    document.getElementById("answer").textContent = yes ? "Yes, by more than the noise." : "Not clearly.";
    document.getElementById("hero-plot").replaceChildren(vsRulePlot(data, rows, overall));
  }
  const findings = findingRows(data, complete);
  if (findings.length) document.getElementById("findings-plot").replaceChildren(findingsPlot(findings));
  document.getElementById("category-plot").replaceChildren(categoryPlot(data, main, summary));
  document.getElementById("coverage-plot").replaceChildren(coveragePlot(data, main));

  const text = answerText(data, overall);
  const partialNote = text?.partial ? h("p", { class: "note partial-note" }, text.partial) : null;
  const toggle = h("div", { class: "seg", role: "group", "aria-label": "Batches shown" },
    h("button", { type: "button", "aria-pressed": "true", "data-set": "main" }, "Main batches"),
    h("button", { type: "button", "aria-pressed": "false", "data-set": "all" }, "All batches, ablations and partial runs"));
  const board = h("div", {});
  const draw = (set) => {
    toggle.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.set === set)));
    board.replaceChildren(set === "main" ? "" : partialNote ?? "", scoreboard(data, set === "main" ? main : data.solvers, summary));
  };
  toggle.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) draw(b.dataset.set); });
  root.replaceChildren(h("div", { class: "board-tools" }, toggle, legend()), board);
  draw("main");
  document.getElementById("generated").replaceChildren(
    `Results generated ${data.generated} from the run records with `, command("python -m rootcause site"), ".");
}

/** The scoreboard table: one run strip per incident and solver, accuracy per category, for the solvers shown. */
function scoreboard(data, solvers, summary) {
  const slots = stripSlots(data);
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

  const table = h("table", { class: solvers.length > 6 ? "scoreboard dense" : "scoreboard" },
    h("caption", { class: "visually-hidden" },
      "Scoreboard: one mark per recorded run, for each incident and solver, with accuracy by category"),
    head, groups, foot);
  return h("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": "Scoreboard" }, table);
}

// ---------------------------------------------------------------- incident page

/** svgEl("line", {x1, ...}): h() for SVG, which needs createElementNS. Only attributes and child nodes, never markup. */
function svgEl(tag, attrs = {}, ...kids) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, v);
  node.append(...kids.filter(Boolean));
  return node;
}

const fact = (term, ...detail) => h("div", {}, h("dt", {}, term), h("dd", {}, ...detail));

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
let windowEndS = 300;  // seconds from the alert to the snapshot's end: the incident JSON's window_end_s (the scenario's settle_s)

function sparkline(o) {
  const g = sparkGeometry(o, windowEndS);
  if (!g) return rawOutput({ output: o, truncated: false });
  const { W, H, at } = g;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "spark", role: "img", "aria-label": g.label },
    g.after ? svgEl("rect", { x: at, y: 0, width: W - at, height: H, class: "spark-after" }) : null,
    g.alert ? svgEl("line", { x1: at, x2: at, y1: 0, y2: H, class: "spark-alert", "vector-effect": "non-scaling-stroke" }) : null,
    svgEl("polyline", { points: g.points, class: "spark-line", "vector-effect": "non-scaling-stroke" }));
  return h("figure", { class: "spark-fig" },
    svg,
    h("div", { class: "spark-range", "aria-hidden": "true" }, h("span", {}, `max ${num(g.hi)}`), h("span", {}, `min ${num(g.lo)}`)),
    h("figcaption", { class: "spark-axis" },
      h("span", {}, minutes(g.t0)),
      g.alert ? h("span", { class: "spark-zero", style: `left: ${g.alertLeft}` }, "alert") : null,
      h("span", {}, minutes(g.t1))),
    g.stopped ? note(g.stopped) : null);
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
    h("p", { class: "out-line" }, logsLine(o)),
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
  const notes = trimNotes(o);
  try {
    return [RENDER[step.tool](o), note(notes.tool), note(notes.site)];
  } catch {
    return rawOutput(step);   // a shape the renderer does not expect is still shown, as text
  }
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
  const alertQuote = h("blockquote", {}, h("p", {}));
  const alertCaption = h("figcaption", {});
  const heldout = !data.heldout ? null : data.heldout_viewed
    ? h("span", { class: "heldout" }, "Held out. Agent v1’s tool output on this incident was viewed once during development; see the ",
      h("a", { href: `${REPORT}#provenance` }, "disclosure in the report"), ".")
    : h("span", { class: "heldout" }, "Held out: not used while developing the agents.");

  root.replaceChildren(
    h("header", { class: "incident-head" },
      h("h1", {}, data.id),
      h("p", { class: "incident-meta" },
        category ? `${category[0]}: ${category[1]}.` : `${categoryName(data.category)}.`,
        heldout),
      h("figure", { class: "alert-quote" }, alertQuote, alertCaption)),
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
    const shown = alertFor(data, state.solver);   // the vague-alert ablations were given another alert
    alertQuote.firstChild.textContent = shown.alert;
    alertCaption.textContent = shown.caption;
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
  /** ?step=N opens the replay partway: the first N steps shown (the verdict after the last step), scrolled to the latest. */
  function openAt(n) {
    const items = [...body.querySelectorAll(".step"), body.querySelector(".verdict")].filter(Boolean);
    const shown = Math.min(Math.max(0, n), items.length);
    items.forEach((el, i) => el.classList.toggle("pending", i >= shown));
    if (shown) items[shown - 1].scrollIntoView({ block: "end" });
    status.textContent = shown === items.length ? "Replay finished. The verdict is shown." : `Step ${shown} of ${items.length - 1}`;
  }

  const asked = state.run;
  draw();
  const step = Number.parseInt(query.get("step"), 10);
  if (Number.isFinite(step)) openAt(step);
  if (Object.hasOwn(runs, state.solver) && runs[state.solver].length) syncURL();
  if (query.has("run") && asked !== state.run) status.textContent = `Run ${query.get("run")} was not recorded, so run ${state.run} is shown.`;
}

// ---------------------------------------------------------------- dispatch

/** The share card (card.html): the hero's answer and plot alone, at a fixed 1280x640, to screenshot as assets/card.png. */
async function renderCard() {
  const data = await loadJSON("data/index.json");
  if (!data?.solvers?.length) return;
  const summary = Object.fromEntries(data.solvers.map((s) =>
    [s, Object.fromEntries((data.summary[s] || []).map((r) => [r.category, r]))]));
  const overall = Object.fromEntries(data.solvers.map((s) => [s, summary[s]["all incidents"]]));
  const rows = vsRuleRows(data, mainSolvers(data, overall));
  if (!rows.length) return;
  document.getElementById("answer").textContent = rows.some((r) => r.ci[0] > 0) ? "Yes, by more than the noise." : "Not clearly.";
  document.getElementById("hero-plot").replaceChildren(vsRulePlot(data, rows, overall));
}

const pages = {
  index: renderIndex,
  incident: renderIncident,
  card: renderCard,
};
Promise.resolve(pages[document.body.dataset.page]?.()).catch((err) => {  // malformed data must not leave "Loading" up
  console.error(err);
  const root = document.querySelector("[data-root]") ?? document.querySelector("main");
  root.replaceChildren(h("p", { class: "status" }, "These results could not be read. Rebuild them with ",
    command("python -m rootcause site"), "."));
});

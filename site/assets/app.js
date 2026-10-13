// RootCause replay site: one ES module for every page. <body data-page="..."> picks the renderer (see the bottom).
// Shared helpers come first; each page's renderer follows.

export const CATEGORIES = {
  easy: ["Easy", "one loud fault"],
  "hard-cross-service": ["Cross-service", "the symptom shows up in a different service from the cause"],
  "hard-silent": ["Silent", "latency or resource faults with no errors"],
  "hard-noisy": ["Noisy", "a real fault plus a decoy traffic flood"],
  "hard-two-faults": ["Two-fault", "both causes must be named"],
  control: ["Control", "nothing is broken; the right answer is “no incident”"],
};

export const SOLVERS = {
  heuristic: ["Heuristic", "the one-line rule"],
  "agent-v0": ["Agent v0", "naive tools"],
  "agent-v1": ["Agent v1", "change-aware tools"],
  "agent-v1-nopriors": ["V1 without priors", "ablation of agent v1"],
  "agent-v1-vague": ["V1 with vague alerts", "ablation of agent v1"],
};

export const solverName = (s) => (SOLVERS[s] || [s])[0];
export const categoryName = (c) => (CATEGORIES[c] || [c])[0];
export const pct = (x) => `${Math.round(x * 100)}%`;
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** h("a", {href, class}, ...children): build an element; strings become text nodes, so data is never parsed as HTML. */
export function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  return node;
}

/** Fetch JSON relative to the page; null when it is missing or unreadable. */
export async function loadJSON(path) {
  try {
    const res = await fetch(path);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** A run's score as a mark: 1 is correct, 0 wrong, anything between partly correct (two-fault, one cause of two). */
export function mark(correct) {
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
  const spread = row.accuracy_std === null ? null : `± ${Math.round(row.accuracy_std * 100)}, `;
  return h("td", { class: "num" },
    h("span", { class: "acc" }, pct(row.accuracy_mean)),
    h("span", { class: "acc-detail" }, spread, `${runs} each`));
}

function legend() {
  const item = (cls, glyph, text) => h("li", {}, h("span", { class: `tile ${cls}`, "aria-hidden": "true" }, glyph), text);
  return h("ul", { class: "legend", "aria-label": "Key" },
    item("hit", "✓", "correct"), item("miss", "✗", "wrong"),
    item("part", "½", "partly correct (one of two causes)"), item("empty", "", "not run yet"));
}

/** "Right on the 16 fault incidents: heuristic 59% and agent v0 41%." plus a note for each partial batch. */
function answer(data, overall) {
  const shown = data.solvers.filter((s) => overall[s]);
  if (!shown.length) return null;
  const n = overall[shown[0]].expected ?? overall[shown[0]].scenarios;
  const parts = shown.map((s) => `${solverName(s).toLowerCase()} ${pct(overall[s].accuracy_mean)}`);
  const list = new Intl.ListFormat("en", { type: "conjunction" }).format(parts);
  const partial = shown.filter((s) => overall[s].records_min !== overall[s].records_max)
    .map((s) => `${solverName(s)} is a partial batch so far (${overall[s].records_min}–${overall[s].records_max} runs per incident).`);
  return h("p", { class: "answer" }, `Right on the ${n} fault incidents: ${list}. `, partial.join(" "));
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
  const slots = Object.fromEntries(solvers.map((s) =>
    [s, Math.max(0, ...data.incidents.map((i) => (i.results[s] || []).length))]));
  const summary = Object.fromEntries(solvers.map((s) =>
    [s, Object.fromEntries((data.summary[s] || []).map((r) => [r.category, r]))]));
  const width = solvers.length + 2;

  const head = h("thead", {}, h("tr", {},
    h("th", { scope: "col", class: "incident" }, "Incident"),
    h("th", { scope: "col" }, "True cause"),
    solvers.map((s) => h("th", { scope: "col", class: "solver" },
      solverName(s), SOLVERS[s] ? h("span", { class: "sub" }, SOLVERS[s][1]) : null))));

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

  const table = h("table", { class: "scoreboard" },
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

// ---------------------------------------------------------------- dispatch

const pages = {
  index: () => { guardFigures(); return renderIndex(); },
};
pages[document.body.dataset.page]?.();

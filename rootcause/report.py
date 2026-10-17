"""Turn every stored run record into docs/results/report.md plus two figures. A solver with no records shows "not run"."""
import itertools
import math
import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; must precede pyplot
import matplotlib.pyplot as plt  # noqa: E402

from rootcause import config, evaluate, scenarios  # noqa: E402
from rootcause.evaluate import fmt2, runs_range  # noqa: E402

# the figures show the heuristic and each model's v0 / v1; ablations are in the tables and paired comparisons only
FIGURE_SOLVERS = ("heuristic", "agent-v0", "agent-v1", "agent-v0-nemotron", "agent-v1-nemotron")
# categorical palette; one fixed colour per solver in both charts
COLOURS = {"heuristic": "#2a78d6", "agent-v0": "#eb6834", "agent-v1": "#1baf7a", "agent-v0-nemotron": "#b9a6ea",
           "agent-v1-nemotron": "#7d5ccf"}
SPLITS = ("all", "tune", "heldout")
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
NOT_RUN = "not run"
DISCLOSURE = ("During agent-v1 development, v1 tool output was viewed on one held-out incident (valkey-cart-paused). "
              "The one feature it suggested that no tuning snapshot exercised (an incomplete-services list) was removed "
              "before any v1 run; the other changes from that time (stopped service-map edges, the 'after = 0 can mean "
              "the service stopped reporting' caveat) are each exercised by the tuning snapshot payment-unreachable.")
MIN_PAIRED = 5  # fewer shared incidents than this: no interval
# (a, b): is a better than b? Each is shown only when both have records.
PAIRS = [("agent-v0", "heuristic"), ("agent-v1", "heuristic"), ("agent-v1", "agent-v0"),
         ("agent-v1-nopriors", "agent-v1"), ("agent-v1-vague", "agent-v1"), ("agent-v0-nemotron", "heuristic"), ("agent-v1-nemotron", "heuristic"),
         ("agent-v1-nemotron", "agent-v1"), ("agent-v1-nemotron", "agent-v0-nemotron"),
         ("agent-v1-nemotron-nopriors", "agent-v1-nemotron"), ("agent-v1-nemotron-vague", "agent-v1-nemotron"),
         ("agent-v1-nemotron-steps30", "agent-v1-nemotron")]
FLASH_NOTE = ("A Flash vs Flash-Lite comparison is absent: Flash's free tier allows 20 requests/day and one agent run "
              "takes about 12-15 requests (up to 17), so the Gemini agents run on `gemini-3.5-flash-lite` only. The model comparison is instead "
              "agent-v1-nemotron: agent v1 unchanged (prompt, tools, step limit) on `nvidia/nemotron-3-super-120b-a12b` "
              "through NVIDIA's free trial endpoint.")


def _table(header, rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(r) + " |" for r in rows])


def _acc(row):
    """mean ± sd (scenarios in the split / library, runs per scenario): small n and partial batches stay visible."""
    if row is None:
        return "-"
    runs = runs_range(row["records_min"], row["records_max"])
    n = f"{row['scenarios']}/{row['expected'] or row['scenarios']}"
    return f"{fmt2(row['accuracy_mean'])} ± {fmt2(row['accuracy_std'])} ({n} sc, {runs} run{'' if runs == '1' else 's'})"


def _shortfall(data, solver, split):
    """(fewest, most runs per library scenario in the split, runs done, runs planned) when some scenario has fewer runs
    than evaluate.planned_runs(solver); None for a complete batch or a solver with no runs in the split."""
    counts = {}
    for r in data["records"][solver]:
        if evaluate.in_split(r["scenario"], split):
            counts[r["scenario"]] = counts.get(r["scenario"], 0) + 1
    per = [counts.get(x.id, 0) for x in scenarios.load_all() if evaluate.in_split(x.id, split)]
    planned = evaluate.planned_runs(solver)
    if not sum(per) or min(per) >= planned:
        return None
    return min(per), max(per), sum(per), planned * len(per)


def _partial(data, solver, split):
    """"1-2 runs per scenario, 32/100 runs" (done / planned) for a partial batch, else None."""
    if not (s := _shortfall(data, solver, split)):
        return None
    lo, hi, done, planned = s
    return f"{runs_range(lo, hi)} runs per scenario, {done}/{planned} runs"


def _label(data, solver):
    """Figure legend label: "agent-v0 (partial, 32/100)" for a partial batch over all scenarios."""
    s = _shortfall(data, solver, "all")
    return f"{solver} (partial, {s[2]}/{s[3]})" if s else solver


def _rows(data, split, solvers):
    """{solver: {category: summary row}}; empty for a solver with no records in the split."""
    return {s: {r["category"]: r for r in data["summaries"][split][s]} for s in solvers}


def _categories(rows):
    return [c for c in evaluate.ORDER + ["all incidents"] if any(c in r for r in rows.values())]


def _accuracy_tables(data, solvers):
    out = ["## Accuracy by category",
           "Accuracy is the mean over scenarios of each scenario's mean; ± is the sd across run indices "
           "(shown when at least two complete runs exist). The held-out split was frozen before any agent-v1 tuning."]
    for split in SPLITS:
        rows = _rows(data, split, solvers)
        cats = _categories(rows)
        body = [[c] + [NOT_RUN if not rows[s] else _acc(rows[s].get(c)) for s in solvers] for c in cats]
        out += [f"### Split: {split}", _table(["category"] + solvers, body) if cats else f"No records in the {split} split."]
        out += [f"{s}: partial batch ({p})" for s in solvers if (p := _partial(data, s, split))]
        if split == "heldout":
            out.append("Held-out categories have one scenario each; read the all-incidents row.")
    return out


def _rate_section(data, solvers, title, note, columns, skip=lambda s: None):
    """columns: [(header, category row, key)] read from the all split; skip(solver) may return a replacement cell."""
    rows = _rows(data, "all", solvers)
    body = [[s] + [NOT_RUN if not rows[s] else skip(s) or fmt2(rows[s].get(cat, {}).get(key)) for _, cat, key in columns] for s in solvers]
    return [title, note, _table(["solver"] + [h for h, _, _ in columns], body)]


def _cost(data, solvers):
    heads = ["solver", "runs with usage / records", "requests (mean)", "requests (max)", "prompt tokens (mean)",
             "completion tokens (mean)", "tokens per correct run"]
    body = []
    for s in solvers:
        u = evaluate.usage(data["records"][s])
        if not data["records"][s]:
            body.append([s] + [NOT_RUN] * 6)
        elif u is None:
            body.append([s, f"0 / {len(data['records'][s])}"] + ["-"] * 5)
        else:
            body.append([s, f"{u['runs']} / {len(data['records'][s])}", fmt2(u["requests_mean"]), str(u["requests_max"]), f"{u['prompt_tokens_mean']:.0f}",
                         f"{u['completion_tokens_mean']:.0f}", "-" if u["tokens_per_correct"] is None else f"{u['tokens_per_correct']:.0f}"])
    return ["## Cost", "The heuristic makes no model calls, so it has no token usage.", _table(heads, body)]


def _means(records):
    """{scenario: (mean score over its runs, number of runs)}."""
    by = {}
    for r in records:
        by.setdefault(r["scenario"], []).append(r["score"]["correct"])
    return {sid: (sum(v) / len(v), len(v)) for sid, v in by.items()}


def paired(a, b, draws=10000, seed=0):
    """Compare two solvers' per-incident mean scores ({scenario: mean}) on the incidents both ran: wins/ties/losses of
    a over b, the mean difference, and a 95% percentile bootstrap CI that resamples incidents (None below MIN_PAIRED
    incidents or when every difference is the same). None if no incident is shared."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return None
    d = [a[s] - b[s] for s in shared]
    rng, n = random.Random(seed), len(d)
    ci = None  # too few incidents, or all differences equal: resampling would print a falsely certain interval
    if n >= MIN_PAIRED and len(set(d)) > 1:
        boot = sorted(sum(rng.choices(d, k=n)) / n for _ in range(draws))
        ci = (boot[int(0.025 * draws)], boot[int(0.975 * draws) - 1])
    return {"n": n, "wins": sum(x > 0 for x in d), "ties": sum(x == 0 for x in d), "losses": sum(x < 0 for x in d),
            "mean_diff": sum(d) / n, "ci": ci}


def _paired_section(data, solvers):
    faults = {s.id for s in scenarios.load_all() if s.category != "control"}
    rows, partial = [], {}
    for a, b in PAIRS:
        if a in solvers and b in solvers and data["records"][a] and data["records"][b]:
            ma, mb = ({sid: m for sid, (m, _) in _means(data["records"][s]).items() if sid in faults} for s in (a, b))
            p = paired(ma, mb)
            if p:
                ci = f"{p['ci'][0]:+.2f} to {p['ci'][1]:+.2f}" if p["ci"] else "n/a (too few incidents or no spread)"
                rows.append([f"{a} vs {b}", f"{p['n']}/{len(faults)}", f"{p['wins']} / {p['ties']} / {p['losses']}",
                             f"{p['mean_diff']:+.2f}", ci])
                partial.update({s: note for s in (a, b) if (note := _partial(data, s, "all"))})
    return ["## Paired comparisons (all split, fault incidents)",
            "Each solver's mean score per incident, compared on the incidents both have run. Wins / ties / losses count "
            "incidents where the first solver scored higher / the same / lower, by any margin. A per-incident mean of 0.5 "
            "can mean one of two causes found or half of the runs right. The 95% interval is a percentile bootstrap over "
            "incidents (10,000 resamples, fixed seed); at this few incidents it is approximate and somewhat too narrow, and "
            f"it is not given below {MIN_PAIRED} shared incidents. An interval that includes 0 means this benchmark cannot "
            "tell the two apart.",
            _table(["comparison", "incidents", "wins / ties / losses", "mean difference", "95% interval"], rows)
            if rows else "No pair of solvers has run a shared fault incident yet.",
            *(f"{s}: partial batch ({note})" for s, note in partial.items())]


FAILURE_MODES = ("said no incident", "named the top-changed service", "true cause ranked 2nd or 3rd",
                 "found one of two causes", "another wrong service", "abstained")


def failure_modes(records, accept, top):
    """Count each wrong fault-incident run by how it went wrong. accept: {scenario: accepted service names};
    top: {scenario: the service with the largest rise in its change table} (empty without snapshots)."""
    counts = dict.fromkeys(FAILURE_MODES, 0)
    for r in records:
        if r["category"] == "control" or r["score"]["correct"] >= 1:
            continue
        rep, ok = r["report"], accept.get(r["scenario"], set())
        named = [c["service"] for c in rep.get("causes") or []]
        if rep["verdict"] == "no_incident":
            mode = "said no incident"
        elif rep["verdict"] != "incident":
            mode = "abstained"
        elif r["score"]["correct"] > 0:
            mode = "found one of two causes"
        elif ok & set(named[1:]):  # it named the cause, just not first: say that before anything else
            mode = "true cause ranked 2nd or 3rd"
        elif named and named[0] == top.get(r["scenario"]):
            mode = "named the top-changed service"
        else:
            mode = "another wrong service"
        counts[mode] += 1
    return {m: n for m, n in counts.items() if n}


def _top_changed():
    """{scenario: service with the largest rise (not request rate)} from the recorded snapshots; {} without them."""
    from rootcause import snapshot, summary
    try:
        lib = scenarios.load_all()
        rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", [s.id for s in lib], valid_only=True)
        out = {}
        for sid, row in rows.items():
            ups = [c for c in summary.changes(snapshot.load(row["path"])) if c["direction"] == "up" and c["signal"] != "rps"]
            if ups:
                out[sid] = ups[0]["service"]
        return out
    except OSError:
        return {}


def _failure_section(data, solvers):
    accept = {s.id: {a for c in s.truth.get("causes", []) for a in c["accept"]} for s in scenarios.load_all()}
    top, rows = _top_changed(), []
    for s in solvers:
        modes = failure_modes(data["records"][s], accept, top)
        if data["records"][s]:
            rows.append([s, str(sum(modes.values()))] + [str(modes.get(m, 0)) for m in FAILURE_MODES])
    return ["## Failure modes (all split, wrong fault-incident runs)",
            "How each wrong run on a fault incident went wrong. The top-changed service is the one with the largest rise "
            "in the incident's change table, usually where the symptom shows; naming it is the heuristic's whole method and "
            "its typical mistake." + ("" if top else " (Recorded snapshots not found, so that column is folded into "
                                                     "'another wrong service'.)"),
            _table(["solver", "wrong runs", *FAILURE_MODES], rows) if rows else "No runs yet."]


def _step_limit_section(data, solvers):
    from rootcause.agent import MAX_STEPS  # lazily: the report needs no model client otherwise
    rows = []
    for s in solvers:
        recs = [r for r in data["records"][s] if r["category"] != "control" and "turns" in r]
        if not recs:
            continue
        hit = [r for r in recs if r["turns"] >= MAX_STEPS]
        free = [r for r in recs if r["turns"] < MAX_STEPS]
        acc = lambda rs: fmt2(sum(r["score"]["correct"] for r in rs) / len(rs)) if rs else "-"
        rows.append([s, str(len(recs)), f"{len(hit)} ({len(hit) / len(recs):.0%})",
                     f"{sum(r['report']['verdict'] == 'no_incident' for r in hit)} of {len(hit)}", acc(hit), acc(free)])
    return ["## Step limit (all split, fault runs)",
            f"An agent that is still calling tools after {MAX_STEPS} model turns is told to give its final answer. "
            "This splits each agent's fault runs by whether that happened: how many hit the limit, how many of those then "
            "answered \"no incident\", and the accuracy (mean over runs, not per scenario) with and without hitting it.",
            _table(["solver", "fault runs", "hit the limit", "then said no incident", "accuracy when hit",
                    "accuracy otherwise"], rows) if rows else "No agent runs yet."]


def _agents(data, solvers):
    """Solvers with a stated confidence and more than one run on some scenario: the agents, not the one-run baselines."""
    return [s for s in solvers if any(n > 1 for _, n in _means(data["records"][s]).values())
            and any(evaluate.confidence(r) is not None for r in data["records"][s])]


def _top(r):
    """The run's top answer: its first cause's service, or the verdict when it names no cause."""
    causes = r["report"].get("causes") or []
    return causes[0]["service"] if causes else r["report"]["verdict"]


def agreement(records):
    """(scenarios with at least 2 runs, how many of those have every run giving the same top answer, the mean over those
    scenarios of the share of run pairs that agree); None when no scenario has 2 runs."""
    by = {}
    for r in records:
        by.setdefault(r["scenario"], []).append(_top(r))
    multi = [v for v in by.values() if len(v) >= 2]
    if not multi:
        return None
    pairs = [sum(a == b for a, b in itertools.combinations(v, 2)) / math.comb(len(v), 2) for v in multi]
    return len(multi), sum(len(set(v)) == 1 for v in multi), sum(pairs) / len(pairs)


def calibration(records, bins=5):
    """Record-level: mean stated confidence, accuracy (mean `correct`), expected calibration error over `bins`
    equal-width confidence bins and Brier score, over the records with a numeric confidence (skipped: the rest)."""
    pts = [(c, r["score"]["correct"]) for r in records if (c := evaluate.confidence(r)) is not None]
    if not pts:
        return None
    by = {}
    for c, y in pts:
        by.setdefault(min(max(int(c * bins), 0), bins - 1), []).append((c, y))
    mean = lambda xs: sum(xs) / len(xs)
    return {"runs": len(pts), "skipped": len(records) - len(pts), "confidence": mean([c for c, _ in pts]),
            "accuracy": mean([y for _, y in pts]),
            "ece": sum(len(b) / len(pts) * abs(mean([c for c, _ in b]) - mean([y for _, y in b])) for b in by.values()),
            "brier": mean([(c - y) ** 2 for c, y in pts])}


def _partials(data, solvers):
    return [f"{s}: partial batch ({p})" for s in solvers if (p := _partial(data, s, "all"))]


def _agreement_section(data, solvers):
    agents, rows = _agents(data, solvers), []
    for s in agents:
        if a := agreement(data["records"][s]):
            rows.append([s, str(a[0]), f"{a[1]} of {a[0]}", fmt2(a[2])])
    return ["## Run-to-run agreement (all incidents)",
            "The agents run at temperature 0, yet their runs still differ, so this measures how far a single run can be "
            "trusted. A run's top answer is its first cause's service, or its verdict when it names no cause. Pairwise "
            "agreement is the share of run pairs on a scenario that give the same top answer, averaged over the "
            "scenarios with at least 2 runs; controls included. With fewer runs per scenario every run agrees more "
            "easily, so compare complete batches only.",
            _table(["solver", "scenarios with 2+ runs", "every run agrees", "pairwise agreement"], rows)
            if rows else "No agent has two runs of a scenario yet.", *_partials(data, agents)]


def _calibration_section(data, solvers):
    agents, rows, cal = _agents(data, solvers), [], {}
    for s in agents:
        if c := calibration(data["records"][s]):
            cal[s] = c
            rows.append([s, str(c["runs"]), fmt2(c["confidence"]), fmt2(c["accuracy"]), fmt2(c["ece"]), fmt2(c["brier"])])
    over = [s for s, c in cal.items() if c["confidence"] > c["accuracy"]]
    if not cal:
        verdict = ""
    elif len(over) == len(cal):
        verdict = "Every agent here states a mean confidence above its accuracy: all of them are overconfident."
    elif over:
        verdict = (f"Mean confidence is above accuracy (overconfident) for {', '.join(over)}, and not for "
                   f"{', '.join(s for s in cal if s not in over)}.")
    else:
        verdict = "No agent here states a mean confidence above its accuracy."
    skipped = [f"{s}: {c['skipped']}" for s, c in cal.items() if c["skipped"]]
    return ["## Calibration (all incidents, record-level)",
            "A well-calibrated agent's mean stated confidence matches its accuracy. Accuracy here is the mean `correct` "
            "over runs, controls included, not the tables' mean over scenarios. ECE (expected calibration error) splits "
            "the runs into 5 equal-width confidence bins and sums, over the bins, the bin's share of runs times "
            "|mean confidence - accuracy|. Brier is the mean of (confidence - correct)^2. Lower is better for both. "
            + verdict,
            _table(["solver", "runs", "mean confidence", "accuracy", "ECE", "Brier"], rows) if rows else "No agent runs yet.",
            *(["Runs without a numeric confidence are skipped: " + ", ".join(skipped) + "."] if skipped else []),
            *_partials(data, agents)]


def _per_scenario(data, solvers):
    means = {s: _means(data["records"][s]) for s in solvers}
    one = lambda s, sid: f"{fmt2(means[s][sid][0])} ({means[s][sid][1]} run{'' if means[s][sid][1] == 1 else 's'})" if sid in means[s] else "-"
    cell = lambda s, sid: NOT_RUN if not data["records"][s] else one(s, sid)
    body = [[x.id + ("*" if x.id in config.HELDOUT else ""), x.category] + [cell(s, x.id) for s in solvers] for x in scenarios.load_all()]
    return ["## Per-scenario accuracy", "`*` marks held-out scenarios; each cell is the mean over that scenario's runs, with the number of runs.", _table(["scenario", "category"] + solvers, body)]


def _coverage_section(data, solvers):
    out = ["## Accuracy vs coverage (all split, record-level)", "![accuracy vs coverage](figures/coverage.png)",
           "Coverage is the fraction of all runs whose answer is at or above the confidence threshold (abstentions never count). "
           "Accuracy here is over answered runs only, so the lowest-threshold point can exceed the tables' accuracy, which counts abstentions as wrong."]
    for s in solvers:
        if not s.startswith("agent") or not data["records"][s]:
            continue
        curve = evaluate.coverage_curve(data["records"][s])
        if not curve:
            out.append(f"{s}: every run abstained, so there is no curve.")
            continue
        p = min(curve, key=lambda p: abs(p["coverage"] - 0.5))
        out.append(f"{s}: accuracy {fmt2(p['accuracy'])} at {p['coverage']:.0%} coverage "
                   f"(the curve point nearest 50%, confidence >= {fmt2(p['threshold'])})."
                   + (f" Partial batch ({note}): treat with caution." if (note := _partial(data, s, "all")) else ""))
    return out


def _evidence_skip(data):
    """Replacement cell for a solver whose evidence cannot be summarised as grounded/distinctive rates, else None."""
    def skip(s):
        checked = [r["evidence_check"] for r in data["records"][s] if "evidence_check" in r]
        if not checked:
            return "n/a (predates evidence checks)"
        kinds = [i.get("kind") for c in checked for i in c.get("items") or []]
        return "n/a (free-text evidence)" if kinds and all(k == "text" for k in kinds) else None
    return skip


def _provenance(data, solvers):
    lines = [f"{s}: " + (", ".join(sorted({r.get("code") or "unknown" for r in data["records"][s]})) if data["records"][s] else NOT_RUN)
             for s in solvers]
    return ["## Provenance", "Code versions (git short sha) of the records behind each solver:", "\n".join(f"- {l}" for l in lines), DISCLOSURE]


def _not_run(data, solvers):
    missing = [s for s in solvers if not data["records"][s]]
    return ["## Not run", ("Solvers with no recorded runs: " + ", ".join(missing) + ".") if missing else "Every listed solver has recorded runs.",
            FLASH_NOTE]


def _chart(figsize, title, xlabel, ylabel, draw, path):
    """draw(ax) returns True if it plotted anything; otherwise the chart says so instead of being blank."""
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_ylim(0, 1.05)
    ok = draw(ax)
    ax.set_title(title, loc="left", fontsize=12, color=INK)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    if ok:
        if figsize[0] >= 8:  # wide grouped bars: legend below the axis, outside the plot
            ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncols=min(3, len(ax.get_legend_handles_labels()[0])))
        else:
            ax.legend(frameon=False, fontsize=8, loc="best")
    else:
        ax.text(0.5, 0.5, "no runs recorded", ha="center", color=MUTED, transform=ax.transAxes)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def _bars(data, solvers):
    rows = _rows(data, "all", solvers)
    shown, cats = [s for s in solvers if rows[s] and s in FIGURE_SOLVERS], _categories(rows)

    def draw(ax):
        width = 0.8 / max(len(shown), 1)
        ax.set_ylim(0, 1.22)  # headroom for the value labels
        ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
        for i, s in enumerate(shown):
            have = [j for j, c in enumerate(cats) if c in rows[s]]  # no record in a category: no bar, not a zero bar
            xs = [j + (i - (len(shown) - 1) / 2) * width for j in have]
            vals = [rows[s][cats[j]]["accuracy_mean"] for j in have]
            sds = [rows[s][cats[j]]["accuracy_std"] for j in have]  # NaN where there is no sd: no error bar, not a zero-width one
            lo = [float("nan") if sd is None else min(sd, v) for v, sd in zip(vals, sds)]  # accuracy lives in [0, 1]
            hi = [float("nan") if sd is None else min(sd, 1 - v) for v, sd in zip(vals, sds)]
            ax.bar(xs, vals, width, yerr=[lo, hi], color=COLOURS.get(s, "#8a8a85"), edgecolor=SURFACE, linewidth=1, label=_label(data, s),
                   ecolor=MUTED, capsize=2)
            for x, v, h in zip(xs, vals, hi):
                ax.text(x, v + (0 if h != h else h) + 0.015, f"{v:.2f}", ha="center", va="bottom", rotation=90, fontsize=7, color=INK)
        ax.set_xticks(range(len(cats)), cats, fontsize=8)
        return bool(shown)
    return draw


def _lines(data, solvers):
    def draw(ax):
        drawn = False
        for s in (s for s in solvers if s in FIGURE_SOLVERS):
            curve = evaluate.coverage_curve(data["records"][s]) if s.startswith("agent") else []
            if curve:
                drawn = True
                ax.plot([p["coverage"] for p in curve], [p["accuracy"] for p in curve], marker="o", markersize=6, linewidth=2,
                        color=COLOURS.get(s, "#8a8a85"), label=_label(data, s))
        ax.set_xlim(0, 1.05)
        return drawn
    return draw


def build(out_dir=config.ROOT / "docs" / "results", runs_dir=evaluate.RUNS_DIR, solvers=None):
    """Write out_dir/report.md and out_dir/figures/*.png from the records under runs_dir; return the report path.
    solvers: default evaluate.listed_solvers (the built-in ones, then any other with records)."""
    out_dir, solvers = Path(out_dir), list(evaluate.listed_solvers(runs_dir) if solvers is None else solvers)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    data = {"records": {s: evaluate.load_records(s, runs_dir) for s in solvers},
            "summaries": {sp: {s: evaluate.summarise(s, runs_dir, evaluate.expected_counts(sp), sp) for s in solvers} for sp in SPLITS}}
    _chart((9, 4.5), "Accuracy by incident category (all scenarios)", "incident category",
           "accuracy (fraction correct)", _bars(data, solvers), out_dir / "figures" / "accuracy_by_category.png")
    _chart((6.5, 4.5), "Accuracy vs coverage by confidence threshold", "coverage (fraction of runs answered above threshold)",
           "accuracy (fraction of covered runs correct)", _lines(data, solvers), out_dir / "figures" / "coverage.png")
    sections = [["# RootCause evaluation report"], _accuracy_tables(data, solvers),
                ["![accuracy by category](figures/accuracy_by_category.png)",
                 "Bars: accuracy over all scenarios; error bars ± sd across run indices, clipped to 0-1 (none when fewer than two complete runs). "
                 "A solver with no record in a category has no bar there."],
                _rate_section(data, solvers, "## False alarms and abstentions (all split)",
                              "False alarm = claiming an incident on a control; abstain = insufficient evidence on an incident.",
                              [("control false-alarm rate", "control", "false_alarm"), ("incident abstain rate", "all incidents", "abstain")]),
                _rate_section(data, solvers, "## Evidence (all split, incidents)",
                              "Grounded = cited evidence exists in the snapshot; distinctive = it also looks anomalous against the baseline "
                              "(neither proves that the incident caused it).",
                              [("grounded", "all incidents", "grounded"), ("distinctive", "all incidents", "distinctive")],
                              skip=_evidence_skip(data)),
                _paired_section(data, solvers), _failure_section(data, solvers), _step_limit_section(data, solvers), _agreement_section(data, solvers),
                _calibration_section(data, solvers), _cost(data, solvers), _per_scenario(data, solvers), _coverage_section(data, solvers), _provenance(data, solvers), _not_run(data, solvers)]
    path = out_dir / "report.md"
    path.write_text("\n\n".join("\n\n".join(s) for s in sections) + "\n", encoding="utf-8")
    return path

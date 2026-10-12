"""Turn every stored run record into docs/results/report.md plus two figures. A solver with no records shows "not run"."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; must precede pyplot
import matplotlib.pyplot as plt  # noqa: E402

from rootcause import config, evaluate, scenarios  # noqa: E402

SOLVER_ORDER = ["heuristic", "agent-v0", "agent-v1", "agent-v1-nopriors", "agent-v1-vague"]
# dataviz categorical slots 1-5 (light surface, validated); one fixed colour per solver in both charts
COLOURS = dict(zip(SOLVER_ORDER, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]))
SPLITS = ("all", "tune", "heldout")
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
NOT_RUN = "not run"
FLASH_NOTE = ("A Flash vs Flash-Lite comparison is absent: Flash's free tier allows 20 requests/day and one agent run "
              "takes about 10, so the agent runs on `gemini-3.5-flash-lite` only.")


def _f(x):
    return "-" if x is None else f"{x:.2f}"


def _table(header, rows):
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(r) + " |" for r in rows])


def _acc(row):
    if row is None:
        return "-"
    return _f(row["accuracy_mean"]) + ("" if row["accuracy_std"] is None else f" ± {_f(row['accuracy_std'])}")


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
    return out


def _rate_section(data, solvers, title, note, columns):
    """columns: [(header, category row, key)] read from the all split."""
    rows = _rows(data, "all", solvers)
    body = [[s] + [NOT_RUN if not rows[s] else _f(rows[s].get(cat, {}).get(key)) for _, cat, key in columns] for s in solvers]
    return [title, note, _table(["solver"] + [h for h, _, _ in columns], body)]


def _cost(data, solvers):
    heads = ["solver", "runs with usage", "requests (mean)", "requests (max)", "prompt tokens (mean)",
             "completion tokens (mean)", "tokens per correct run"]
    body = []
    for s in solvers:
        u = evaluate.usage(data["records"][s])
        if not data["records"][s]:
            body.append([s] + [NOT_RUN] * 6)
        elif u is None:
            body.append([s] + ["-"] * 6)
        else:
            body.append([s, str(u["runs"]), _f(u["requests_mean"]), str(u["requests_max"]), f"{u['prompt_tokens_mean']:.0f}",
                         f"{u['completion_tokens_mean']:.0f}", "-" if u["tokens_per_correct"] is None else f"{u['tokens_per_correct']:.0f}"])
    return ["## Cost", "The heuristic makes no model calls, so it has no token usage.", _table(heads, body)]


def _per_scenario(data, solvers):
    means = {}
    for s in solvers:
        by = {}
        for r in data["records"][s]:
            by.setdefault(r["scenario"], []).append(r["score"]["correct"])
        means[s] = {sid: sum(v) / len(v) for sid, v in by.items()}
    cell = lambda s, sid: NOT_RUN if not data["records"][s] else _f(means[s].get(sid))
    body = [[x.id + ("*" if x.id in config.HELDOUT else ""), x.category] + [cell(s, x.id) for s in solvers] for x in scenarios.load_all()]
    return ["## Per-scenario accuracy", "`*` marks held-out scenarios (mean over runs).", _table(["scenario", "category"] + solvers, body)]


def _coverage_section(data, solvers):
    out = ["## Accuracy vs coverage", "![accuracy vs coverage](figures/coverage.png)",
           "Coverage is the fraction of all runs whose answer is at or above the confidence threshold (abstentions never count)."]
    for s in solvers:
        if not s.startswith("agent") or not data["records"][s]:
            continue
        curve = evaluate.coverage_curve(data["records"][s])
        if not curve:
            out.append(f"{s}: every run abstained, so there is no curve.")
            continue
        p = min(curve, key=lambda p: abs(p["coverage"] - 0.5))
        out.append(f"{s}: accuracy {_f(p['accuracy'])} at {p['coverage']:.0%} coverage "
                   f"(the curve point nearest 50%, confidence >= {_f(p['threshold'])}).")
    return out


def _not_run(data, solvers):
    missing = [s for s in solvers if not data["records"][s]]
    return ["## Not run", ("Solvers with no recorded runs: " + ", ".join(missing) + ".") if missing else "Every listed solver has recorded runs.",
            FLASH_NOTE]


def _chart(figsize, title, xlabel, ylabel, draw, path):
    """draw(ax) returns True if it plotted anything; otherwise the chart says so instead of being blank."""
    fig, ax = plt.subplots(figsize=figsize)
    ok = draw(ax)
    ax.set_title(title, loc="left", fontsize=12, color=INK)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    if ok:
        ax.legend(frameon=False, fontsize=8, loc="best" if figsize[0] < 8 else "upper right", ncols=2 if figsize[0] >= 8 else 1)
    else:
        ax.text(0.5, 0.5, "no runs recorded", ha="center", color=MUTED, transform=ax.transAxes)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def _bars(data, solvers):
    rows = _rows(data, "all", solvers)
    shown, cats = [s for s in solvers if rows[s]], _categories(rows)

    def draw(ax):
        width = 0.8 / max(len(shown), 1)
        for i, s in enumerate(shown):
            xs = [j + (i - (len(shown) - 1) / 2) * width for j in range(len(cats))]
            get = lambda c, k: (rows[s].get(c) or {}).get(k)
            sd = [get(c, "accuracy_std") for c in cats]  # NaN where there is no sd: no error bar rather than a zero-width one
            ax.bar(xs, [get(c, "accuracy_mean") or 0 for c in cats], width, yerr=[float("nan") if x is None else x for x in sd],
                   color=COLOURS.get(s, "#8a8a85"), edgecolor=SURFACE, linewidth=1, label=s, ecolor=MUTED, capsize=2)
        ax.set_xticks(range(len(cats)), cats, fontsize=8)
        return bool(shown)
    return draw


def _lines(data, solvers):
    def draw(ax):
        drawn = False
        for s in solvers:
            curve = evaluate.coverage_curve(data["records"][s]) if s.startswith("agent") else []
            if curve:
                drawn = True
                ax.plot([p["coverage"] for p in curve], [p["accuracy"] for p in curve], marker="o", markersize=6, linewidth=2,
                        color=COLOURS.get(s, "#8a8a85"), label=s)
        ax.set_xlim(0, 1.05)
        return drawn
    return draw


def build(out_dir=config.ROOT / "docs" / "results", runs_dir=evaluate.RUNS_DIR, solvers=SOLVER_ORDER):
    """Write out_dir/report.md and out_dir/figures/*.png from the records under runs_dir; return the report path."""
    out_dir, solvers = Path(out_dir), list(solvers)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    data = {"records": {s: evaluate.load_records(s, runs_dir) for s in solvers},
            "summaries": {sp: {s: evaluate.summarise(s, runs_dir, evaluate.expected_counts(sp), sp) for s in solvers} for sp in SPLITS}}
    _chart((9, 4.5), "Accuracy by incident category (all scenarios)", "incident category",
           "accuracy (fraction correct; error bars ± sd across runs)", _bars(data, solvers), out_dir / "figures" / "accuracy_by_category.png")
    _chart((6.5, 4.5), "Accuracy vs coverage by confidence threshold", "coverage (fraction of runs answered above threshold)",
           "accuracy (fraction of covered runs correct)", _lines(data, solvers), out_dir / "figures" / "coverage.png")
    sections = [["# RootCause evaluation report"], _accuracy_tables(data, solvers),
                ["![accuracy by category](figures/accuracy_by_category.png)"],
                _rate_section(data, solvers, "## False alarms and abstentions (all split)",
                              "False alarm = claiming an incident on a control; abstain = insufficient evidence on an incident.",
                              [("control false-alarm rate", "control", "false_alarm"), ("incident abstain rate", "all incidents", "abstain")]),
                _rate_section(data, solvers, "## Evidence (all split, incidents)",
                              "Grounded = cited evidence exists in the snapshot; distinctive = it also separates this incident from the baseline.",
                              [("grounded", "all incidents", "grounded"), ("distinctive", "all incidents", "distinctive")]),
                _cost(data, solvers), _per_scenario(data, solvers), _coverage_section(data, solvers), _not_run(data, solvers)]
    path = out_dir / "report.md"
    path.write_text("\n\n".join("\n\n".join(s) for s in sections) + "\n", encoding="utf-8")
    return path

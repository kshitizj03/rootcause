"""Run a solver over the recorded snapshots (N runs each), score against truth, and summarise per category.

The solver only ever receives snapshot.load(path); truth.json is read after solve() returns."""
import json
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path

from rootcause import config, scenarios, snapshot
from rootcause.score import report_to_dict, score

RUNS_DIR = config.DATA / "runs"


def targets(ids=None):
    lib = {s.id: s for s in scenarios.load_all()}
    rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", ids or list(lib))
    return [(sid, lib[sid].category, rows[sid]["path"]) for sid in sorted(rows) if sid in lib]


def run(solver_name, solve, runs=1, ids=None, out_dir=RUNS_DIR, stop_on=(), clock=time.time):
    """Write out_dir/solver_name/<scenario>__<k>.json per run; existing records are kept (resumable)."""
    d = Path(out_dir) / solver_name
    d.mkdir(parents=True, exist_ok=True)
    done = 0
    for sid, category, path in targets(ids):
        for k in range(runs):
            f = d / f"{sid}__{k}.json"
            if f.exists():
                continue
            snap = snapshot.load(path)
            t0 = clock()
            try:
                report, info = solve(snap)
            except stop_on as e:  # e.g. the daily free-tier quota: stop cleanly, resume tomorrow
                return {"completed": done, "stopped": f"{type(e).__name__}: {e}"}
            rec = {**info, "scenario": sid, "category": category, "run": k, "seconds": clock() - t0,  # info first: it can't overwrite these
                   "report": report_to_dict(report), "score": score(report, snapshot.load_truth(path))}
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            tmp.replace(f)  # a crash mid-write never leaves a half record that resume would skip
            done += 1
    return {"completed": done, "stopped": None}


def _row(category, recs):
    by_run = defaultdict(list)
    for r in recs:
        by_run[r["run"]].append(r["score"]["correct"])
    accs = [sum(v) / len(v) for v in by_run.values()]
    ft = [r["score"]["fault_type_ok"] for r in recs if r["score"]["fault_type_ok"] is not None]
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    per_scenario = Counter(r["scenario"] for r in recs).values()  # uneven when a batch stopped part-way
    return {"category": category, "scenarios": len(per_scenario), "runs": len(by_run),
            "records_min": min(per_scenario), "records_max": max(per_scenario),
            "accuracy_mean": mean(accs), "accuracy_std": statistics.pstdev(accs) if accs else None,
            "top3": mean([float(r["score"]["top3"]) for r in recs]),
            "fault_type": mean([float(x) for x in ft]),
            "false_alarm": mean([float(r["score"]["false_alarm"]) for r in recs]),
            "abstain": mean([float(r["score"]["abstained"]) for r in recs])}


ORDER = ["easy", "hard-cross-service", "hard-silent", "hard-noisy", "hard-two-faults", "control"]


def summarise(solver_name, out_dir=RUNS_DIR):
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(out_dir) / solver_name).glob("*.json"))]
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)
    rows = [_row(c, by_cat[c]) for c in sorted(by_cat, key=lambda c: ORDER.index(c) if c in ORDER else 99)]
    incidents = [r for r in recs if r["category"] != "control"]
    if incidents:
        rows.append(_row("all incidents", incidents))
    return rows


def format_summary(rows):
    fmt = lambda x: "-" if x is None else f"{x:.2f}"
    out = ["| category | scenarios | runs | accuracy (mean +/- sd) | top-3 | fault type | false alarm | abstain |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lo, hi = r["records_min"], r["records_max"]  # runs per scenario: "3-5" flags a partial batch
        runs = str(lo) if lo == hi else f"{lo}-{hi}"
        out.append(f"| {r['category']} | {r['scenarios']} | {runs} | {fmt(r['accuracy_mean'])} +/- "
                   f"{fmt(r['accuracy_std'])} | {fmt(r['top3'])} | {fmt(r['fault_type'])} | "
                   f"{fmt(r['false_alarm'])} | {fmt(r['abstain'])} |")
    return "\n".join(out)

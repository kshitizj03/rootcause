"""Run a solver over the recorded snapshots (N runs each), score against truth, and summarise per category.

The solver only ever receives snapshot.load(path); truth.json is read after solve() returns."""
import json
import statistics
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from rootcause import config, scenarios, snapshot
from rootcause.score import report_to_dict, score

RUNS_DIR = config.DATA / "runs"


def targets(ids=None):
    lib = {s.id: s for s in scenarios.load_all()}
    rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", ids or list(lib))
    return [(sid, lib[sid].category, rows[sid]["path"]) for sid in sorted(rows) if sid in lib]


def code_version(cwd=config.ROOT):
    """Git short sha of HEAD, plus -dirty if tracked files have uncommitted changes; "unknown" without git."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
    try:
        sha, dirty = git("rev-parse", "--short", "HEAD"), git("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return (sha + ("-dirty" if dirty else "")) if sha else "unknown"


def run(solver_name, solve, runs=1, ids=None, out_dir=RUNS_DIR, stop_on=(), clock=time.time):
    """Write out_dir/solver_name/<scenario>__<k>.json per run; existing records are kept (resumable).
    Run-major (every scenario once, then again), so a quota stop leaves each scenario with the same number of runs."""
    d = Path(out_dir) / solver_name
    d.mkdir(parents=True, exist_ok=True)
    done, code = 0, code_version()
    for k in range(runs):
        for sid, category, path in targets(ids):
            f = d / f"{sid}__{k}.json"
            if f.exists():
                continue
            snap = snapshot.load(path)
            t0 = clock()
            try:
                report, info = solve(snap)
            except stop_on as e:  # e.g. the daily free-tier quota: stop cleanly, resume tomorrow
                return {"completed": done, "stopped": f"{type(e).__name__}: {e}"}
            rec = {**info, "scenario": sid, "category": category, "run": k, "seconds": clock() - t0, "code": code,  # info first: it can't overwrite these
                   "report": report_to_dict(report), "score": score(report, snapshot.load_truth(path))}
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            tmp.replace(f)  # a crash mid-write never leaves a half record that resume would skip
            done += 1
    return {"completed": done, "stopped": None}


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def _row(category, recs, expected=None):
    """Every rate is the mean over scenarios of each scenario's own mean, so a scenario with more records (a partial
    batch) does not outweigh the rest. The sd covers only run indices that have a record for every scenario."""
    by_scn, by_run = defaultdict(list), defaultdict(dict)
    for r in recs:
        by_scn[r["scenario"]].append(r)
        by_run[r["run"]][r["scenario"]] = r["score"]["correct"]

    def rate(f):  # None values (e.g. fault_type_ok on controls) are skipped
        per = [_mean(float(v) for v in map(f, rs) if v is not None) for rs in by_scn.values()]
        return _mean(x for x in per if x is not None)

    complete = [_mean(v.values()) for v in by_run.values() if len(v) == len(by_scn)]
    per_scenario = [len(rs) for rs in by_scn.values()]  # uneven when a batch stopped part-way
    return {"category": category, "scenarios": len(by_scn), "expected": expected, "runs": len(by_run),
            "records_min": min(per_scenario), "records_max": max(per_scenario),
            "accuracy_mean": rate(lambda r: r["score"]["correct"]),
            "accuracy_std": statistics.pstdev(complete) if len(complete) >= 2 else None,
            "top3": rate(lambda r: r["score"]["top3"]),
            "fault_type": rate(lambda r: r["score"]["fault_type_ok"]),
            "false_alarm": rate(lambda r: r["score"]["false_alarm"]),
            "abstain": rate(lambda r: r["score"]["abstained"]),
            "errors": rate(lambda r: None if "error" not in r else r["error"] is not None)}  # None: solver never sets it


ORDER = ["easy", "hard-cross-service", "hard-silent", "hard-noisy", "hard-two-faults", "control"]


def summarise(solver_name, out_dir=RUNS_DIR, expected=None, split=None):
    """expected: {category: number of scenarios in the library}, to show how complete each row is.
    split: None/"all", "tune" (not config.HELDOUT) or "heldout"."""
    expected = expected or {}
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(out_dir) / solver_name).glob("*.json"))]
    if split == "tune":
        recs = [r for r in recs if r["scenario"] not in config.HELDOUT]
    elif split == "heldout":
        recs = [r for r in recs if r["scenario"] in config.HELDOUT]
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)
    rows = [_row(c, by_cat[c], expected.get(c)) for c in sorted(by_cat, key=lambda c: ORDER.index(c) if c in ORDER else 99)]
    incidents = [r for r in recs if r["category"] != "control"]
    if incidents:
        rows.append(_row("all incidents", incidents, sum(n for c, n in expected.items() if c != "control") or None))
    return rows


def format_summary(rows):
    fmt = lambda x: "-" if x is None else f"{x:.2f}"
    out = ["| category | scenarios | runs | accuracy (mean +/- sd) | top-3 | fault type (cause+type) | false alarm | abstain | errors |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lo, hi = r["records_min"], r["records_max"]  # runs per scenario: "3-5" flags a partial batch
        runs = str(lo) if lo == hi else f"{lo}-{hi}"
        n, exp = r["scenarios"], r.get("expected")
        scenarios_ = str(n) if exp in (None, n) else f"{n}/{exp}"
        control = r["category"] == "control"
        out.append(f"| {r['category']} | {scenarios_} | {runs} | {fmt(r['accuracy_mean'])} +/- "
                   f"{fmt(r['accuracy_std'])} | {'-' if control else fmt(r['top3'])} | {fmt(r['fault_type'])} | "
                   f"{fmt(r['false_alarm']) if control else '-'} | {fmt(r['abstain'])} | {fmt(r['errors'])} |")
    out.append("two-fault: accuracy = fraction of causes found; top-3 = both causes found")
    return "\n".join(out)

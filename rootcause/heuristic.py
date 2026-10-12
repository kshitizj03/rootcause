"""Baseline: name the service whose fault-indicating signal rose the most against its baseline window."""
from rootcause import summary
from rootcause.score import Cause, Report

THRESHOLD = 1.0  # relative rise >= 1.0 against max(baseline, floor); fixed a priori, never tuned to results
RANKED = ("error_ratio", "p95_ms", "mem_mb", "cpu_cores", "restarts")  # rps is load, not a fault signal


def diagnose(snap, threshold=THRESHOLD):
    rows = [r for r in summary.changes(snap)
            if r["signal"] in RANKED and r["direction"] == "up" and r["score"] >= threshold]
    if not rows:
        return Report("no_incident", (), (), 0.5)
    causes, seen = [], set()
    for r in rows:
        if r["service"] not in seen:
            seen.add(r["service"])
            causes.append(Cause(r["service"], r["fault_type"]))
        if len(causes) == 3:
            break
    evidence = tuple(f"{r['service']} {r['signal']} {r['baseline']:.3g} -> {r['value']:.3g}" for r in rows[:3])
    top = rows[0]["score"]
    return Report("incident", tuple(causes), evidence, top / (1 + top))


def solve(snap):
    return diagnose(snap), {"solver": "heuristic"}

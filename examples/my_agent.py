"""A tiny baseline to copy: names the service whose error ratio rose most after the alert.

    python -m rootcause eval-custom examples.my_agent:solve --name my-agent

It is deterministic, so one run per incident (the default) is enough; give --runs N for a solver that varies.

Replace solve() with your own agent. docs/benchmark.md describes the snapshot it gets and the report it returns."""


def _mean(points, start, end):
    values = [v for t, v in points if start <= t < end]
    return sum(values) / len(values) if values else None


def solve(snap):
    meta, rises = snap["meta"], {}
    for service, points in snap["metrics"].get("error_ratio", {}).items():
        before = _mean(points, meta["baseline_start"], meta["fault_start"])
        after = _mean(points, meta["fault_start"], float("inf"))
        if before is not None and after is not None:
            rises[service] = after - before
    top = max(rises, key=rises.get, default=None)
    if top is None or rises[top] < 0.05:  # no error ratio rose by 5 points: call it healthy
        return {"verdict": "no_incident", "causes": [], "evidence": [], "confidence": 0.5}, {}
    evidence = [{"kind": "metric", "service": top, "signal": "error_ratio", "claim": f"rose by {rises[top]:.3f}"}]
    return {"verdict": "incident", "causes": [{"service": top, "fault_type": "errors"}], "evidence": evidence,
            "confidence": 0.6}, {}

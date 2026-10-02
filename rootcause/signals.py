"""Derived per-service signals (PromQL), window statistics, and scenario signal checks."""
from rootcause import config

_CALLS = "traces_span_metrics_calls_total"
_RATE = f"sum by (service_name) (rate({_CALLS}[2m]))"
SIGNALS = {
    "rps": ("service", _RATE),
    "error_ratio": ("service", f'(sum by (service_name) (rate({_CALLS}{{status_code="STATUS_CODE_ERROR"}}[2m])) '
                               f"or 0 * {_RATE}) / {_RATE}"),
    "p95_ms": ("service", "histogram_quantile(0.95, sum by (service_name, le) "
                          "(rate(traces_span_metrics_duration_milliseconds_bucket[2m])))"),
    "mem_mb": ("container", "max by (container_name) (container_memory_usage_total_bytes) / 1e6"),
    "cpu_cores": ("container", "max by (container_name) (rate(container_cpu_usage_nanoseconds_total[2m])) / 1e9"),
    "uptime_s": ("container", "max by (container_name) (container_uptime_seconds)"),
}
# Ratios divide by max(baseline, floor) so a near-zero baseline doesn't explode the ratio.
FLOORS = {"rps": 0.1, "error_ratio": 0.01, "p95_ms": 5.0, "mem_mb": 5.0, "cpu_cores": 0.02, "restarts": 1.0}


def fetch_series(prom_range, start, end, step):
    out = {}
    for signal, (kind, query) in SIGNALS.items():
        label = "service_name" if kind == "service" else "container_name"
        out[signal] = {}
        for r in prom_range(query, start, end, step):
            name = r["metric"].get(label)
            if not name or name in config.HIDDEN_SERVICES or name not in config.KNOWN_TARGETS:
                continue
            out[signal][name] = [[float(t), float(v)] for t, v in r["values"] if v not in ("NaN", "+Inf", "-Inf")]
    return out


def window_stat(points, start, end, stat="mean"):
    vals = [v for t, v in points if start <= t <= end]
    if not vals:
        return None
    return max(vals) if stat == "max" else sum(vals) / len(vals)


def restarts(points, start, end):
    """Uptime drops inside [start, end]; the last point before start is included so a restart right at the
    window edge still counts."""
    before = [v for t, v in points if t < start][-1:]
    vals = before + [v for t, v in points if start <= t <= end]
    return sum(1 for a, b in zip(vals, vals[1:]) if b < a)


def evaluate(checks, metrics, baseline, fault):
    results = []
    for chk in checks:
        signal = chk["signal"]
        source = metrics.get("uptime_s" if signal == "restarts" else signal, {})
        targets = sorted(source) if chk["service"] == "*" else [chk["service"]]
        for target in targets:
            pts = source.get(target)
            if signal == "restarts" and pts:
                value, base = restarts(pts, *fault), restarts(pts, *baseline)
            elif pts:
                stat = chk.get("stat", "mean")
                value, base = window_stat(pts, *fault, stat), window_stat(pts, *baseline, stat)
            else:
                value = base = None
            if value is None:
                results.append({**chk, "target": target, "passed": False, "reason": "no data"})
                continue
            ok = True
            if "at_least" in chk:
                ok = ok and value >= chk["at_least"]
            if "at_most" in chk:
                ok = ok and value <= chk["at_most"]
            if "ratio_at_least" in chk:
                ok = ok and value / max(base or 0.0, FLOORS[signal]) >= chk["ratio_at_least"]
            results.append({**chk, "target": target, "value": value, "baseline": base, "passed": bool(ok)})
    return results

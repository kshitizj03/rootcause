"""Agent v1 toolset: every v0 tool plus change-aware views (baseline window vs fault window) and a service map.

Reads only a loaded snapshot (meta, metrics, spans, logs). t < 0 is before the alert, t >= 0 after it."""
from collections import defaultdict

from rootcause import config, summary, tools


def _fmt(row):
    sign = "+" if row["direction"] == "up" else "-"
    return {"service": row["service"], "signal": row["signal"], "before": tools._sig(row["baseline"]),
            "after": tools._sig(row["value"]), "change": f"{sign}{row['score']:.1f}x" if row["score"] >= 10 else f"{sign}{row['score']:.2f}x"}


def top_changes(snap, n=10, include_load=False):
    n = max(1, min(40, int(10 if n is None else n)))
    rows = [r for r in summary.changes(snap) if include_load is True or str(include_load).lower() == "true" or r["signal"] != "rps"]
    seen = {r["service"] for r in summary.changes(snap)}
    incomplete = sorted({s for series in snap["metrics"].values() for s in series} - seen)
    return {"changes": [_fmt(r) for r in rows[:n]], "incomplete": incomplete,
            "note": f"change = |after - before| / max(before, small floor); before = {config.BASELINE_S // 60} min before the alert, "
                    f"after = from {config.RAMP_S} s after it; after = 0 can mean the service stopped reporting, not recovery. "
                    "incomplete = services with metrics but no complete before/after windows"}


def service_health(snap, service):
    rows = [r for r in summary.changes(snap) if r["service"] == service]
    if not rows and service in tools._services(snap):
        return {"service": service, "signals": [],
                "note": "no complete before/after metric windows for this service (it may have started or stopped reporting around the alert)"}
    if not rows:
        return {"error": f"no metrics for {service!r}", "valid_services": tools._services(snap)}
    return {"service": service, "signals": [_fmt(r) for r in rows]}


def service_map(snap, limit=20):
    limit = max(1, min(60, int(20 if limit is None else limit)))
    t0 = snap["meta"]["fault_start"] * 1000
    oldest = t0 - config.CAPTURE_LOOKBACK_S * 1000  # some snapshots hold stale spans from hours earlier; ignore them
    by_id = {s["span_id"]: s for s in snap["spans"]}
    edges = defaultdict(lambda: {"calls_before": 0, "calls_after": 0, "errors_before": 0, "errors_after": 0})
    for s in snap["spans"]:
        parent = by_id.get(s["parent_id"])
        if not parent or parent["service"] == s["service"] or s["start_ms"] < oldest:  # only the child span's age is filtered
            continue
        e = edges[(parent["service"], s["service"])]
        when = "after" if s["start_ms"] >= t0 else "before"
        e[f"calls_{when}"] += 1
        e[f"errors_{when}"] += bool(s["error"])
    for e in edges.values():
        if e["calls_before"] > 0 and e["calls_after"] == 0:
            e["stopped"] = True
    ranked = sorted(edges.items(), key=lambda kv: (-max(0, kv[1]["errors_after"] - kv[1]["errors_before"]),
                                                   -(kv[1]["calls_before"] if kv[1].get("stopped") else 0), -kv[1]["calls_after"], kv[0]))
    return {"edges": [{"caller": a, "callee": b, **v} for (a, b), v in ranked[:limit]],
            "note": f"edges from parent/child spans across services; before = the {config.CAPTURE_LOOKBACK_S // 60} min before the alert, after = t >= 0; stopped = calls vanished after the alert"}


TOOLS = {**tools.TOOLS, "top_changes": top_changes, "service_health": service_health, "service_map": service_map}
SCHEMAS = tools.SCHEMAS + [
    {"type": "function", "function": {"name": "top_changes", "description": f"Start here. Every service's signals ranked by how much they changed from the {config.BASELINE_S // 60} minutes before the alert to after it (error_ratio, p95_ms, mem_mb peak, cpu_cores, restarts; rps only with include_load).",
                                      "parameters": {"type": "object", "properties": {"n": {"type": "integer"}, "include_load": {"type": "boolean"}}}}},
    {"type": "function", "function": {"name": "service_health", "description": "All signals of one service, before vs after the alert, with the change.",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "service_map", "description": "Which service calls which (from traces), with call and error counts before vs after the alert; edges whose errors rose come first, then edges whose calls stopped after the alert (flagged \"stopped\").",
                                      "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
]


def call(snap, name, raw_args):
    return tools.call(snap, name, raw_args, registry=TOOLS)

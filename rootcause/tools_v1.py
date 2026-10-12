"""Agent v1 toolset: every v0 tool plus change-aware views (baseline window vs fault window) and a service map.

Reads only a loaded snapshot (meta, metrics, spans, logs). t < 0 is before the alert, t >= 0 after it."""
from collections import defaultdict

from rootcause import summary, tools


def _fmt(row):
    sign = "+" if row["direction"] == "up" else "-"
    return {"service": row["service"], "signal": row["signal"], "before": tools._sig(row["baseline"]),
            "after": tools._sig(row["value"]), "change": f"{sign}{row['score']:.1f}x" if row["score"] >= 10 else f"{sign}{row['score']:.2f}x"}


def top_changes(snap, n=10, include_load=False):
    n = max(1, min(40, int(10 if n is None else n)))
    rows = [r for r in summary.changes(snap) if include_load is True or str(include_load).lower() == "true" or r["signal"] != "rps"]
    return {"changes": [_fmt(r) for r in rows[:n]],
            "note": "change = |after - before| / max(before, small floor); before = 15 min before the alert, after = from 1 min after it"}


def service_health(snap, service):
    rows = [r for r in summary.changes(snap) if r["service"] == service]
    if not rows:
        return {"error": f"no metrics for {service!r}", "valid_services": tools._services(snap)}
    return {"service": service, "signals": [_fmt(r) for r in rows]}


def service_map(snap, limit=20):
    limit = max(1, min(60, int(20 if limit is None else limit)))
    t0 = snap["meta"]["fault_start"] * 1000
    by_id = {s["span_id"]: s for s in snap["spans"]}
    edges = defaultdict(lambda: {"calls_before": 0, "calls_after": 0, "errors_before": 0, "errors_after": 0})
    for s in snap["spans"]:
        parent = by_id.get(s["parent_id"])
        if not parent or parent["service"] == s["service"]:
            continue
        e = edges[(parent["service"], s["service"])]
        when = "after" if s["start_ms"] >= t0 else "before"
        e[f"calls_{when}"] += 1
        e[f"errors_{when}"] += bool(s["error"])
    ranked = sorted(edges.items(), key=lambda kv: (-(kv[1]["errors_after"] - kv[1]["errors_before"]), -kv[1]["calls_after"], kv[0]))
    return {"edges": [{"caller": a, "callee": b, **v} for (a, b), v in ranked[:limit]],
            "note": "edges from parent/child spans across services; before = t < 0, after = t >= 0"}


TOOLS = {**tools.TOOLS, "top_changes": top_changes, "service_health": service_health, "service_map": service_map}
SCHEMAS = tools.SCHEMAS + [
    {"type": "function", "function": {"name": "top_changes", "description": "Start here. Every service's signals ranked by how much they changed from the 15 minutes before the alert to after it (error_ratio, p95_ms, mem_mb peak, cpu_cores, restarts; rps only with include_load).",
                                      "parameters": {"type": "object", "properties": {"n": {"type": "integer"}, "include_load": {"type": "boolean"}}}}},
    {"type": "function", "function": {"name": "service_health", "description": "All signals of one service, before vs after the alert, with the change.",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "service_map", "description": "Which service calls which (from traces), with call and error counts before vs after the alert; edges whose errors rose come first.",
                                      "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
]


def call(snap, name, raw_args):
    return tools.call(snap, name, raw_args, registry=TOOLS)

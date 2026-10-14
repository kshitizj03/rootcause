"""Agent v0 tools: naive, read-only views over one loaded snapshot (meta, metrics, spans, logs only).

Times are seconds relative to the alert (t=0 = meta.fault_start). v0 deliberately has no baseline
comparison or ranking; the change-aware tools are in tools_v1.py (the v0/v1 comparison is the naive vs change-aware
ablation)."""
import json
from collections import Counter
from datetime import datetime, timezone

MAX_TOOL_CHARS = 6000
SIGNAL_NAMES = ("rps", "error_ratio", "p95_ms", "mem_mb", "cpu_cores", "uptime_s")


def round_sig(x):
    return float(f"{x:.4g}") if isinstance(x, (int, float)) else x


def epoch(ts):
    head, _, frac = ts.rstrip("Z").partition(".")
    return datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() + float("0." + (frac or "0"))


def _limit(limit, default):
    return max(1, min(200, int(default if limit is None else limit)))  # models often send explicit nulls


def as_bool(x):
    return x.strip().lower() in ("true", "1", "yes") if isinstance(x, str) else bool(x)


def _window(since, until):
    """(lo, hi) in seconds relative to the alert, both inclusive; None = open-ended."""
    lo = -float("inf") if since is None else float(since)
    hi = float("inf") if until is None else float(until)
    return lo, hi


def services(snap):
    names = {s for series in snap["metrics"].values() for s in series}
    names |= {sp["service"] for sp in snap["spans"]} | {lg["service"] for lg in snap["logs"]}
    return sorted(names)


def list_services(snap):
    return {"services": services(snap)}


def get_metric(snap, service, signal):
    if signal not in SIGNAL_NAMES:
        return {"error": f"unknown signal {signal!r}", "valid_signals": list(SIGNAL_NAMES)}
    series = snap["metrics"].get(signal, {})
    if service not in series:
        return {"error": f"no {signal} series for {service!r}", "valid_services": sorted(series)}
    t0, points, last_minute = snap["meta"]["fault_start"], [], None
    for t, v in series[service]:
        rel = round(t - t0)
        minute = rel // 60
        if minute != last_minute:  # thin to one point per minute
            points.append([rel, round_sig(v)])
            last_minute = minute
    return {"service": service, "signal": signal, "points": points, "note": "t = seconds relative to the alert"}


def search_traces(snap, service, errors_only=False, limit=10, since=None, until=None):
    limit, errors_only, (lo, hi) = _limit(limit, 10), as_bool(errors_only), _window(since, until)
    t0 = snap["meta"]["fault_start"]
    spans = [s for s in snap["spans"] if s["service"] == service and (s["error"] or not errors_only)
             and lo <= s["start_ms"] / 1000 - t0 <= hi]
    if not spans and service not in services(snap):
        return {"error": f"unknown service {service!r}", "valid_services": services(snap)}
    ops = Counter(s["name"] for s in spans)
    msgs = Counter(s["message"][:150] for s in spans if s["error"] and s["message"])
    slow = sorted(spans, key=lambda s: -s["dur_ms"])[:limit]
    return {"service": service, "spans_found": len(spans), "errors": sum(s["error"] for s in spans),
            "operations": dict(ops.most_common(limit)), "error_messages": dict(msgs.most_common(5)),
            "slowest": [{"trace_id": s["trace_id"], "name": s["name"], "dur_ms": round_sig(s["dur_ms"]),
                         "t": round(s["start_ms"] / 1000 - t0), "error": s["error"]} for s in slow]}


def get_trace(snap, trace_id):
    t0 = snap["meta"]["fault_start"]
    spans = sorted((s for s in snap["spans"] if s["trace_id"] == trace_id), key=lambda s: s["start_ms"])
    if not spans:
        return {"error": f"no trace {trace_id!r} in this incident"}
    return {"trace_id": trace_id, "spans": [
        {"service": s["service"], "name": s["name"], "t": round(s["start_ms"] / 1000 - t0), "dur_ms": round_sig(s["dur_ms"]),
         "error": s["error"], "message": s["message"][:200], "parent_id": s["parent_id"], "span_id": s["span_id"]}
        for s in spans[:40]], "total_spans": len(spans)}


def search_logs(snap, service, text="", min_severity=0, limit=20, since=None, until=None):
    limit, min_severity, (lo, hi) = _limit(limit, 20), int(min_severity or 0), _window(since, until)
    t0, needle = snap["meta"]["fault_start"], str(text or "").lower()
    logs = [lg for lg in snap["logs"] if lg["service"] == service and needle in str(lg["body"]).lower()
            and (lg["severity_number"] or 0) >= min_severity and lo <= epoch(lg["ts"]) - t0 <= hi]
    if not logs and service not in services(snap):
        return {"error": f"unknown service {service!r}", "valid_services": services(snap)}
    logs.sort(key=lambda lg: epoch(lg["ts"]))
    return {"service": service, "total": len(logs), "samples": [  # the last `limit` lines of the filtered window
        {"t": round(epoch(lg["ts"]) - t0), "severity": lg["severity"], "body": str(lg["body"])[:200],
         "trace_id": lg["trace_id"]} for lg in logs[-limit:]]}


TOOLS = {"list_services": list_services, "get_metric": get_metric, "search_traces": search_traces,
         "get_trace": get_trace, "search_logs": search_logs}

_STR = {"type": "string"}
_NUM = {"type": "number"}
SCHEMAS = [
    {"type": "function", "function": {"name": "list_services", "description": "List every service and infrastructure container with telemetry in this incident.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_metric", "description": "One metric series for one service, one point per minute, t = seconds relative to the alert (negative = before). Signals: rps, error_ratio, p95_ms, mem_mb, cpu_cores (cores), uptime_s (drops = restarts).",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "signal": {"type": "string", "enum": list(SIGNAL_NAMES)}}, "required": ["service", "signal"]}}},
    {"type": "function", "function": {"name": "search_traces", "description": "Summarise a service's spans: operations, error messages and the slowest spans (with trace ids). since/until select a time window (seconds relative to the alert, inclusive); limit is 1-200.",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "errors_only": {"type": "boolean"}, "limit": {"type": "integer"}, "since": _NUM, "until": _NUM}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "get_trace", "description": "All spans of one trace in start order: service, operation, duration, errors.",
                                      "parameters": {"type": "object", "properties": {"trace_id": _STR}, "required": ["trace_id"]}}},
    {"type": "function", "function": {"name": "search_logs", "description": "A service's log lines oldest to newest; returns the LAST `limit` (1-200, default 20) lines of the filtered window, so narrow with since/until (seconds relative to the alert, inclusive) or text to see earlier lines. min_severity is the OpenTelemetry severity number: 17 = ERROR, 13 = WARN, 9 = INFO. Many lines (e.g. proxy access logs) have no severity and only appear with min_severity=0 (the default); failures are often logged at WARN, so try 13 before concluding logs are clean.",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "text": _STR, "min_severity": {"type": "integer"}, "limit": {"type": "integer"}, "since": _NUM, "until": _NUM}, "required": ["service"]}}},
]


TRUNCATED = ' ... [truncated: reduce limit or add a text/time filter]'


def call(snap, name, raw_args, registry=None):
    """Run one tool by name; never raises. Returns JSON text capped at MAX_TOOL_CHARS."""
    registry = TOOLS if registry is None else registry
    try:
        if name not in registry:
            out = {"error": f"unknown tool {name!r}", "valid_tools": sorted(registry)}
        else:
            args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args or {})
            out = registry[name](snap, **args)
        text = json.dumps(out)
    except Exception as e:  # model-supplied names/args can fail in many ways (e.g. OverflowError on limit=1e999)
        text = json.dumps({"error": f"bad call to {name!r}: {type(e).__name__}: {e}"})
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS - len(TRUNCATED)] + TRUNCATED
    return text

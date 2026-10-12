"""Check that a report's cited evidence exists in the snapshot it was made from (spec section 9).

Two measures per cited item (neither proves the claim it is attached to):
- grounded: the citation exists in the snapshot within the incident window (t >= fault_start).
- distinctive (stricter): the citation also points at something anomalous. A metric must have changed (same as
  grounded); a log quote must appear in no pre-alert log of that service; a trace must contain an error span, or a
  span (of the cited service, else any) lasting longer than that service's pre-alert p95 (an error span anywhere
  in the trace counts: parents inherit their children's errors). Free text is neither."""
import re
import math

from rootcause import summary
from rootcause.tools import _epoch


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _t(ts):
    try:
        return _epoch(ts)
    except (ValueError, TypeError, AttributeError):
        return None  # a malformed timestamp: the line doesn't count


def _p95(values):
    """Nearest-rank 95th percentile: a healthy service's slowest ~5% of spans, so routine tail latency is not 'anomalous'."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def _check(item, snap, rows):
    """-> (grounded, distinctive, reason)"""
    t0 = snap["meta"]["fault_start"]
    if isinstance(item, str) or item.get("kind") == "text":
        return False, False, "free text is not checkable"
    kind = item["kind"]
    if kind == "metric":
        row = rows.get((item["service"], item["signal"]))
        if row is None:
            return False, False, "no such series"
        ok = row["score"] >= 0.5
        return ok, ok, "changed" if ok else "series did not change notably"
    if kind == "trace":
        spans = [s for s in snap["spans"] if s["trace_id"] == item["trace_id"]]
        if not spans:
            return False, False, "no such trace"
        spans = [s for s in spans if s["start_ms"] / 1000 >= t0]
        if not spans:
            return False, False, "trace is before the incident window"
        if item.get("service") and all(s["service"] != item["service"] for s in spans):
            return False, False, "trace has no span of that service in the incident window"

        def slow(s):
            pre = [p["dur_ms"] for p in snap["spans"] if p["service"] == s["service"] and p["start_ms"] / 1000 < t0]
            return bool(pre) and s["dur_ms"] > _p95(pre)
        distinct = any(s["error"] for s in spans) or any(
            slow(s) for s in spans if not item.get("service") or s["service"] == item["service"])
        return True, distinct, "trace found"
    if kind == "log":
        quote = _norm(item["quote"])
        if len(quote) < 8:
            return False, False, "quote too short to be specific"
        lines = [(_t(lg["ts"]), _norm(lg["body"])) for lg in snap["logs"] if lg["service"] == item["service"]]
        lines = [(t, b) for t, b in lines if t is not None and quote in b]
        if not any(t >= t0 for t, _ in lines):
            return False, False, "no such log line in the incident window"
        old = any(t < t0 for t, _ in lines)
        return True, not old, "also logged before the alert" if old else "log line found"
    return False, False, "unknown kind"


def check(report, snap):
    rows = {(r["service"], r["signal"]): r for r in summary.changes(snap)} if report.evidence else {}
    items = []
    for item in report.evidence:
        ok, distinct, reason = _check(item, snap, rows)
        items.append({"kind": "text" if isinstance(item, str) else item["kind"], "grounded": ok,
                      "distinctive": distinct, "reason": reason})
    return {"items": items, "grounded": sum(i["grounded"] for i in items),
            "distinctive": sum(i["distinctive"] for i in items), "total": len(items)}

"""Check that a report's cited evidence exists in the snapshot it was made from (spec section 9)."""
import re

from rootcause import summary
from rootcause.tools import _epoch


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _check(item, snap, rows):
    t0 = snap["meta"]["fault_start"]
    if isinstance(item, str) or item.get("kind") == "text":
        return False, "free text is not checkable"
    kind = item["kind"]
    if kind == "metric":
        row = rows.get((item["service"], item["signal"]))
        if row is None:
            return False, "no such series"
        return (row["score"] >= 0.5, "changed" if row["score"] >= 0.5 else "series did not change notably")
    if kind == "trace":
        spans = [s for s in snap["spans"] if s["trace_id"] == item["trace_id"]]
        if not spans:
            return False, "no such trace"
        spans = [s for s in spans if s["start_ms"] / 1000 >= t0]
        if not spans:
            return False, "trace is before the incident window"
        if item.get("service") and all(s["service"] != item["service"] for s in spans):
            return False, "trace has no span of that service in the incident window"
        return True, "trace found"
    if kind == "log":
        quote = _norm(item["quote"])
        if len(quote) < 8:
            return False, "quote too short to be specific"
        hit = any(lg["service"] == item["service"] and _epoch(lg["ts"]) >= t0 and quote in _norm(lg["body"])
                  for lg in snap["logs"])
        return hit, "log line found" if hit else "no such log line in the incident window"
    return False, "unknown kind"


def check(report, snap):
    """grounded = the citation exists in the snapshot within the incident window; it does not prove the claim."""
    rows = {(r["service"], r["signal"]): r for r in summary.changes(snap)} if report.evidence else {}
    items = []
    for item in report.evidence:
        ok, reason = _check(item, snap, rows)
        items.append({"kind": "text" if isinstance(item, str) else item["kind"], "grounded": ok, "reason": reason})
    return {"items": items, "grounded": sum(i["grounded"] for i in items), "total": len(items)}

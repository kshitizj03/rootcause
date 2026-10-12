"""Builders shared by tests: OTLP payloads, flat spans, a fake clock."""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
FLAGS = FIXTURES / "demo.flagd.json"


def kv(key, value):
    typ = {bool: "boolValue", int: "intValue", float: "doubleValue"}.get(type(value), "stringValue")
    return {"key": key, "value": {typ: str(value) if typ == "intValue" else value}}


def otlp_payload(service, spans):
    """spans: dicts with span_id, name, optional parent, attrs, events [(name, attrs)], error, message."""
    return {"result": {"resourceSpans": [{
        "resource": {"attributes": [kv("service.name", service)]},
        "scopeSpans": [{"spans": [{
            "traceId": "t1", "spanId": s["span_id"], "parentSpanId": s.get("parent", ""), "name": s["name"],
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1250000000",
            "status": {"code": 2, "message": s.get("message", "")} if s.get("error") else {},
            "attributes": [kv(k, v) for k, v in s.get("attrs", {}).items()],
            "events": [{"name": n, "attributes": [kv(k, v) for k, v in a.items()]} for n, a in s.get("events", [])],
        } for s in spans]}],
    }]}}


def flat_span(service="payment", name="charge", attrs=None, events=None, message="", error=False, span_id="s1"):
    return {"trace_id": "t1", "span_id": span_id, "parent_id": "", "service": service, "name": name,
            "start_ms": 1000.0, "dur_ms": 250.0, "error": error, "message": message,
            "attributes": attrs or {}, "events": events or []}


class Clock:
    """Fake time: sleep advances now() and records how long each sleep was."""

    def __init__(self, t=100_000.0):
        self.t = t
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds

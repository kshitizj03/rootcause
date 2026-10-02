from helpers import otlp_payload
from rootcause import backends


def test_flatten_otlp_reads_spans_attributes_events_and_errors():
    payload = otlp_payload("payment", [
        {"span_id": "a", "name": "charge", "error": True, "message": "Invalid token",
         "attrs": {"http.status_code": 500, "ok": False, "ratio": 0.5},
         "events": [("exception", {"exception.message": "boom"})]},
        {"span_id": "b", "parent": "a", "name": "db"},
    ])
    spans = backends.flatten_otlp(payload)
    assert [s["span_id"] for s in spans] == ["a", "b"]
    a, b = spans
    assert a["service"] == "payment" and a["error"] is True and a["message"] == "Invalid token"
    assert a["attributes"] == {"http.status_code": 500, "ok": False, "ratio": 0.5}
    assert a["events"] == [{"name": "exception", "attributes": {"exception.message": "boom"}}]
    assert a["start_ms"] == 1000.0 and a["dur_ms"] == 250.0
    assert b["parent_id"] == "a" and b["error"] is False


def test_flatten_otlp_handles_empty_payload():
    assert backends.flatten_otlp({"result": {"resourceSpans": []}}) == []


def test_flatten_log_supports_nested_and_dotted_resource_keys():
    nested = {"@timestamp": "2026-09-28T10:00:00Z", "resource": {"service": {"name": "cart"}},
              "severity": {"text": "ERROR", "number": 17}, "body": "failed", "traceId": "t9"}
    dotted = {"@timestamp": "x", "resource": {"service.name": "email"}, "body": 42}
    assert backends.flatten_log(nested) == {"ts": "2026-09-28T10:00:00Z", "service": "cart", "severity": "ERROR",
                                            "severity_number": 17, "body": "failed", "trace_id": "t9"}
    assert backends.flatten_log(dotted)["service"] == "email"
    assert backends.flatten_log(dotted)["body"] == "42"


def test_flatten_log_treats_none_body_as_empty_string():
    assert backends.flatten_log({"@timestamp": "t", "body": None})["body"] == ""
    assert backends.flatten_log({"@timestamp": "t"})["body"] == ""


def test_jaeger_raw_404_returns_empty_payload(monkeypatch):
    class MockResponse:
        status_code = 404
    monkeypatch.setattr(backends.requests, "get", lambda *args, **kwargs: MockResponse())
    assert backends.flatten_otlp(backends.jaeger_raw("s", 0, 1, 10)) == []

import gzip
import json

from helpers import FLAGS, flat_span
from rootcause import sanitize

NAMES = sanitize.flag_names(FLAGS)


def test_flag_names_read_from_file():
    assert "paymentFailure" in NAMES and "recommendationCacheFailure" in NAMES


def test_spans_lose_flag_events_attributes_hidden_services_and_flagd_calls():
    spans = [
        flat_span(span_id="keep", attrs={"http.method": "POST", "feature_flag.key": "paymentFailure"},
                  events=[{"name": "feature_flag.evaluation", "attributes": {"feature_flag.result.variant": "on"}},
                          {"name": "exception", "attributes": {"exception.message": "Invalid token"}}],
                  error=True, message="Payment request failed. Invalid token."),
        flat_span(service="flagd", span_id="hidden"),
        flat_span(service="cart", span_id="calls-flagd", attrs={"url.full": "http://flagd:8013/flagd.evaluation.v2.Service/ResolveFloat"}),
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == ["keep"]
    kept = out[0]
    assert kept["attributes"] == {"http.method": "POST"}
    assert [e["name"] for e in kept["events"]] == ["exception"]
    assert kept["message"] == "Payment request failed. Invalid token."
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_logs_are_redacted_and_hidden_services_dropped():
    logs = [{"ts": "t", "service": "checkout", "severity": "INFO", "severity_number": 9,
             "body": "Warning: FeatureFlag 'kafkaQueueProblems' is activated, overloading queue now.", "trace_id": ""},
            {"ts": "t", "service": "flagd", "severity": "INFO", "severity_number": 9, "body": "reload", "trace_id": ""},
            {"ts": "t", "service": "payment", "severity": "ERROR", "severity_number": 17, "body": "Invalid token", "trace_id": "x"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert [l["service"] for l in out] == ["checkout", "payment"]
    assert "overloading queue now" in out[0]["body"] and "[redacted]" in out[0]["body"]
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_find_leaks_catches_names_and_phrases_case_insensitively():
    text = "paymentfailure then Feature Flag then feature_flag.key then FLAGD"
    assert sanitize.find_leaks(text, NAMES) == ["feature flag", "feature_flag", "flagd", "paymentfailure"]


def test_scan_snapshot_reads_plain_and_gz_files(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"rps": {"payment": [[1, 2]]}}))
    with gzip.open(tmp_path / "logs.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"body": "adHighCpu is on"}) + "\n")
    with gzip.open(tmp_path / "spans.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"name": "clean"}) + "\n")
    assert sanitize.scan_snapshot(tmp_path, NAMES) == {"logs.jsonl.gz": ["adhighcpu"]}

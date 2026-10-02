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


def test_redact_handles_unicode_escapes_without_breakage():
    logs = [{"service": "x", "body": "­HighCpu"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert len(out) == 1
    # Verify it doesn't crash and can be serialized (the key issue with json-based redaction)
    assert json.dumps(out)


def test_redact_span_content_name_message_and_event_attributes():
    spans = [
        flat_span(service="payment", span_id="s1",
                  message="adHighCpu occurred",
                  events=[{"name": "log", "attributes": {"msg": "adHighCpu triggered"}}])
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert len(out) == 1
    kept = out[0]
    assert "adHighCpu" not in kept["message"]
    assert "adHighCpu" not in kept["events"][0]["attributes"]["msg"]
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_scan_snapshot_raises_filenotfound_for_missing_files(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({}))
    # logs.jsonl.gz is missing
    (tmp_path / "spans.jsonl.gz").write_text("")
    try:
        sanitize.scan_snapshot(tmp_path, NAMES)
        assert False, "Should have raised FileNotFoundError"
    except FileNotFoundError as e:
        assert "logs.jsonl.gz" in str(e)


def test_find_leaks_separator_tolerant_flag_matching():
    text = "kafka_queue_problems kafka-queue-problems kafka queue problems kafka.queue.problems KAFKA_QUEUE_PROBLEMS"
    hits = sanitize.find_leaks(text, NAMES)
    assert any("kafka" in h for h in hits), f"Should detect kafka variations in {hits}"


def test_hidden_services_case_insensitive_and_span_name_matching():
    spans = [
        flat_span(service="FLAGD", span_id="hidden1"),
        flat_span(service="Flagd", span_id="hidden2"),
        flat_span(name="flagd.evaluation.v1.Service/ResolveBoolean", span_id="hidden3"),
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == [], "Should filter all flagd service/name spans"

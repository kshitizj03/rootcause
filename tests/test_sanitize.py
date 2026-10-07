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


def test_logs_naming_a_flag_are_dropped_and_hidden_services_dropped():
    logs = [{"ts": "t", "service": "checkout", "severity": "INFO", "severity_number": 9,
             "body": "Warning: FeatureFlag 'kafkaQueueProblems' is activated, overloading queue now.", "trace_id": ""},
            {"ts": "t", "service": "flagd", "severity": "INFO", "severity_number": 9, "body": "reload", "trace_id": ""},
            {"ts": "t", "service": "payment", "severity": "ERROR", "severity_number": 17, "body": "Invalid token", "trace_id": "x"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert [l["service"] for l in out] == ["payment"]
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


def test_flagservice_spans_logs_and_leaks_are_caught():
    spans = [flat_span(service="frontend-proxy", span_id="gone", name="router flagservice egress"),
             flat_span(service="frontend-proxy", span_id="stays", name="ingress")]
    assert [s["span_id"] for s in sanitize.sanitize_spans(spans, NAMES)] == ["stays"]
    logs = [{"ts": "t", "service": "frontend-proxy", "severity": "INFO", "severity_number": 9, "trace_id": "",
             "body": "POST /flagservice/x.evaluation.v1.Service/ResolveAll HTTP/1.1 200"},
            {"ts": "t", "service": "frontend-proxy", "severity": "INFO", "severity_number": 9, "trace_id": "",
             "body": "GET /api/cart HTTP/1.1 200"}]
    assert [l["body"] for l in sanitize.sanitize_logs(logs, NAMES)] == ["GET /api/cart HTTP/1.1 200"]
    assert sanitize.find_leaks("POST /flagservice/x", NAMES) == ["flagservice"]


def test_log_dropped_when_any_string_field_matches():
    logs = [{"service": "x", "body": "ok", "attributes": {"k": ["adHighCpu"]}}, {"service": "x", "body": "ok"}]
    assert sanitize.sanitize_logs(logs, NAMES) == [{"service": "x", "body": "ok"}]


def test_redact_handles_unicode_escapes_without_breakage():
    logs = [{"service": "x", "body": "­HighCpu"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert len(out) == 1
    # Verify it doesn't crash and can be serialized (the key issue with json-based redaction)
    assert json.dumps(out)


def test_spans_with_a_match_anywhere_are_dropped_not_redacted():
    spans = [flat_span(span_id="msg", message="adHighCpu occurred"),
             flat_span(span_id="evt", events=[{"name": "log", "attributes": {"msg": "adHighCpu triggered"}}]),
             flat_span(span_id="key", attrs={"adHighCpu": "x"}),
             flat_span(span_id="legacy", message="x [redacted] y"),
             flat_span(span_id="ok", message="Invalid token")]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == ["ok"]
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_legacy_redaction_stubs_are_dropped_and_flagged():
    logs = [{"service": "checkout", "body": "Warning: [redacted] '[redacted]' is activated, overloading queue now."},
            {"service": "checkout", "body": "ok"}]
    assert sanitize.sanitize_logs(logs, NAMES) == [{"service": "checkout", "body": "ok"}]
    assert sanitize.find_leaks("x [redacted] y", NAMES) == ["[redacted]"]


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
    text = "kafka_queue_problems kafka-queue-problems kafka.queue.problems KAFKA_QUEUE_PROBLEMS"
    hits = sanitize.find_leaks(text, NAMES)
    assert any("kafka" in h for h in hits), f"Should detect kafka variations in {hits}"
    # Spaces are NOT separators in flag patterns - ordinary English shouldn't match
    text_with_spaces = "kafka queue problems some payment failure text"
    hits_spaces = sanitize.find_leaks(text_with_spaces, NAMES)
    assert not any("kafka" in h for h in hits_spaces), "Space-separated words should not be leaks"


def test_logs_payment_failure_text_unchanged():
    logs = [{"ts": "t", "service": "payment", "severity": "ERROR", "severity_number": 17,
             "body": "Payment failure: card declined", "trace_id": "x"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert len(out) == 1
    assert out[0]["body"] == "Payment failure: card declined"


def test_span_charge_card_and_payment_failure_unchanged():
    spans = [
        flat_span(service="payment", span_id="s1", name="charge card", message="payment failure")
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert len(out) == 1
    assert out[0]["name"] == "charge card"
    assert out[0]["message"] == "payment failure"


def test_redact_unicode_soft_hyphen_unchanged_and_json_safe():
    # Body with soft hyphen U+00AD followed by HighCpu: the flag "adHighCpu" is NOT present
    # (U+00AD is a single character, not the letters "ad")
    logs = [{"service": "x", "body": "­HighCpu"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert len(out) == 1
    assert out[0]["body"] == "­HighCpu", "Soft hyphen body unchanged"
    assert json.dumps(out)  # Must be serializable


def test_redact_form_feed_with_flagd_unchanged():
    # Form-feed character \f followed by "lagd": doesn't contain "flagd"
    logs = [{"service": "x", "body": "\flagd"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert len(out) == 1
    assert out[0]["body"] == "\flagd", "Form-feed flagd unchanged (form-feed is not 'f')"
    assert json.dumps(out)


def test_hidden_services_case_insensitive_and_span_name_matching():
    spans = [
        flat_span(service="FLAGD", span_id="hidden1"),
        flat_span(service="Flagd", span_id="hidden2"),
        flat_span(name="flagd.evaluation.v1.Service/ResolveBoolean", span_id="hidden3"),
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == [], "Should filter all flagd service/name spans"

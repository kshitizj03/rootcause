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


def test_flag_named_attribute_keys_are_removed_and_the_span_kept():
    # the recommendation service sets demo.feature_flag.recommendation_cache=True only while the fault is on
    spans = [flat_span(span_id="new", attrs={"demo.feature_flag.recommendation_cache": True, "demo.product.count": 10}),
             flat_span(span_id="legacy", attrs={"demo.[redacted].recommendation_cache": True, "demo.product.count": 10}),
             flat_span(span_id="evt", events=[{"name": "log", "attributes": {"adHighCpu": True, "k": 1}}]),
             flat_span(span_id="key", attrs={"adHighCpu": "x", "k": 1})]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == ["new", "legacy", "evt", "key"]
    assert out[0]["attributes"] == out[1]["attributes"] == {"demo.product.count": 10}
    assert out[2]["events"][0]["attributes"] == {"k": 1} and out[3]["attributes"] == {"k": 1}
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_matching_name_or_remaining_value_still_drops_a_span_with_flag_keys():
    spans = [flat_span(span_id="name", name="router flagservice egress", attrs={"demo.feature_flag.x": True}),
             flat_span(span_id="val", attrs={"demo.feature_flag.x": True, "note": "adHighCpu"})]
    assert sanitize.sanitize_spans(spans, NAMES) == []


def test_flag_named_log_keys_are_removed_and_the_log_kept_unless_content_matches():
    logs = [{"service": "x", "body": "ok", "attributes": {"demo.feature_flag.a": True, "n": {"flagd": 1, "m": 2}}},
            {"service": "x", "body": "adHighCpu", "attributes": {"demo.feature_flag.a": True}}]
    assert sanitize.sanitize_logs(logs, NAMES) == [{"service": "x", "body": "ok", "attributes": {"n": {"m": 2}}}]


# --- neutral rewrites: the demo's self-reporting product-catalog error is kept, as a plain error ---

PC_NEW = "Error: Product Catalog Fail Feature Flag Enabled"
PC_LEGACY = "Error: Product Catalog Fail [redacted] Enabled"


def _pc_span(span_id, message, exc):
    return flat_span(service="frontend", span_id=span_id, error=True, message=message,
                     attrs={"exception.message": exc})


def test_product_catalog_failure_spans_are_kept_and_rewritten_to_a_plain_error():
    spans = [_pc_span("new", PC_NEW, "13 INTERNAL: " + PC_NEW),
             _pc_span("legacy", PC_LEGACY, "13 INTERNAL: " + PC_LEGACY)]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == ["new", "legacy"]
    for s in out:
        assert s["message"] == "Error: Product Catalog Fail"
        assert s["attributes"] == {"exception.message": "13 INTERNAL: Error: Product Catalog Fail"}
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_product_catalog_failure_logs_and_event_keys_are_rewritten_too():
    logs = [{"service": "checkout", "body": "failed: " + PC_NEW, "attributes": {PC_LEGACY: 1}}]
    assert sanitize.sanitize_logs(logs, NAMES) == [
        {"service": "checkout", "body": "failed: Error: Product Catalog Fail", "attributes": {"Error: Product Catalog Fail": 1}}]


def test_rewrite_is_case_sensitive_and_real_flag_names_still_drop_the_span():
    spans = [_pc_span("lower", "error: product catalog fail feature flag enabled", ""),
             _pc_span("kafka", "kafkaQueueProblems on", "")]
    assert sanitize.sanitize_spans(spans, NAMES) == []


def _log(service, body):
    return {"ts": "t", "service": service, "severity": "INFO", "severity_number": 9, "body": body, "trace_id": ""}


FAULT_ANNOUNCEMENTS = [
    ("ad", "High CPU-Load problempattern enabled"),
    ("ad", "at oteldemo.problempattern.CpuLoad.run(CpuLoad.java:42)"),
    ("checkout", "Done with #12 messages for overload simulation."),
    ("product-catalog", "lock contention scenario active: holding ACCESS EXCLUSIVE lock on catalog.products"),
    ("product-catalog", "failed to commit lock contention transaction"),
]


def test_fault_announcing_phrases_are_dropped_and_flagged():
    logs = [_log(s, b) for s, b in FAULT_ANNOUNCEMENTS]
    assert sanitize.sanitize_logs(logs, NAMES) == []
    for _, body in FAULT_ANNOUNCEMENTS:
        assert sanitize.find_leaks(body, NAMES), body


def test_generic_overload_and_lock_wording_is_not_a_leak():
    ok = ["server overloaded, shedding load", "ERROR 1205: lock wait timeout exceeded",
          "high lock contention on table orders", "pool overload detected"]
    logs = [_log("cart", b) for b in ok]
    assert sanitize.sanitize_logs(logs, NAMES) == logs
    assert all(sanitize.find_leaks(b, NAMES) == [] for b in ok)


def test_load_generator_logs_and_spans_are_dropped_as_a_hidden_service():
    assert sanitize.sanitize_logs([_log("load-generator", "User flooding homepage 10 times")], NAMES) == []
    spans = [flat_span(service="load-generator", name="user_flood_home", span_id="lg"),
             flat_span(service="frontend", name="GET /", span_id="fe")]
    assert [s["span_id"] for s in sanitize.sanitize_spans(spans, NAMES)] == ["fe"]


def test_phrases_are_narrow_demo_tokens_not_generic_wording():
    for ok in ("known problem patterns in this service", "lock contention transactions rolled back"):
        assert sanitize.find_leaks(ok, NAMES) == [], ok
        assert sanitize.sanitize_logs([_log("cart", ok)], NAMES) != []


def test_scan_snapshot_flags_hidden_service_series_in_metrics(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps(
        {"rps": {"payment": [[1, 2]], "load-generator": [[1, 9]]}}))
    for n in ("logs.jsonl.gz", "spans.jsonl.gz"):
        with gzip.open(tmp_path / n, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"name": "clean"}) + "\n")
    assert sanitize.scan_snapshot(tmp_path, NAMES) == {"metrics.json": ["hidden service: load-generator"]}

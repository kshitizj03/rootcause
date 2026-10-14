import json
from pathlib import Path
from types import SimpleNamespace

from helpers import FLAGS, SCENARIO, T_END, T_INJECT, fake_fetch, flat_log, flat_span, otlp_payload
from rootcause import config, sanitize, snapshot
from rootcause.scenarios import Scenario

NAMES = sanitize.flag_names(FLAGS)


def test_capture_writes_sanitised_valid_snapshot(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(), out_dir=tmp_path, demo_commit="abc")
    path = Path(out["path"])
    assert out["valid"] is True and out["leaks"] == {}
    assert out["scenario"] == "payment-test" and "path" in out

    # Directory name must be opaque (not contain scenario id)
    assert "payment-test" not in path.name
    assert path.name.startswith("incident__")

    for name in ("meta.json", "truth.json", "metrics.json", "spans.jsonl.gz", "logs.jsonl.gz", "validation.json"):
        assert (path / name).exists(), name

    # Verify scenario_id and category are NOT in meta.json or metrics.json
    meta_text = (path / "meta.json").read_text(encoding="utf-8")
    assert "scenario_id" not in meta_text and "category" not in meta_text and "payment-test" not in meta_text
    metrics_text = (path / "metrics.json").read_text(encoding="utf-8")
    assert "payment-test" not in metrics_text

    # Verify scenario_id/category are NOT in spans or logs
    snap = snapshot.load(path)
    assert "scenario_id" not in snap["meta"] and "category" not in snap["meta"]
    assert snap["meta"]["fault_start"] == T_INJECT and snap["meta"]["demo_commit"] == "abc"
    assert "truth" not in snap
    assert [s["span_id"] for s in snap["spans"]] == ["a"]
    assert snap["spans"][0]["events"] == []
    assert {l["body"] for l in snap["logs"]} == {"Payment request failed. Invalid token."}  # flag log dropped

    # Verify scenario_id and category ARE in truth.json
    truth = snapshot.load_truth(path)
    assert truth["scenario_id"] == "payment-test" and truth["category"] == "easy"
    assert truth["causes"] == SCENARIO.truth["causes"]

    assert json.loads((path / "validation.json").read_text(encoding="utf-8"))["valid"] is True


def test_capture_marks_invalid_when_signal_is_too_weak(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(prom_value_after=0.05), out_dir=tmp_path)
    assert out["valid"] is False
    assert out["results"][0]["passed"] is False


def test_capture_empty_spans_and_logs(tmp_path):
    """Empty spans/logs (e.g. control scenarios) still write all three tool files; validation runs cleanly."""
    def empty_fetch():
        def prom_range(query, start, end, step):
            vals = [[t, "0.01"] for t in range(int(start), int(end) + 1, step)]
            return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": vals}]

        def jaeger_raw(service, start, end, limit):
            return {"result": {"resourceSpans": []}}

        def os_logs(query, start, end, size):
            return []

        return SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)

    control_scenario = Scenario(id="control-test", category="control", alert="Baseline with no faults.",
                                inject={}, truth={"causes": []},
                                checks=[{"service": "payment", "signal": "error_ratio", "at_most": 0.05}])
    out = snapshot.capture(control_scenario, T_INJECT, T_END, NAMES, fetch=empty_fetch(), out_dir=tmp_path)
    path = Path(out["path"])

    # All three tool files written, even when empty
    assert (path / "metrics.json").exists()
    assert (path / "spans.jsonl.gz").exists()
    assert (path / "logs.jsonl.gz").exists()

    snap = snapshot.load(path)
    assert snap["spans"] == []
    assert snap["logs"] == []

    # Validation runs cleanly with no leaks and passes the check
    assert out["leaks"] == {}
    validation = json.loads((path / "validation.json").read_text(encoding="utf-8"))
    assert validation["leaks"] == {}
    assert validation["valid"] is True


def test_hidden_services_never_queried(tmp_path):
    """Hidden services (flagd, flagd-ui, load-generator) are never queried for spans or logs, in either window."""
    calls = {"jaeger_raw": [], "os_logs": []}

    def recording_fetch():
        def prom_range(query, start, end, step):
            vals = [[t, "0"] for t in range(int(start), int(end) + 1, step)]
            return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": vals}]

        def jaeger_raw(service, start, end, limit):
            calls["jaeger_raw"].append(service)
            return {"result": {"resourceSpans": []}}

        def os_logs(query, start, end, size):
            calls["os_logs"].append(query)
            return []

        return SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)

    control_scenario = Scenario(id="control-test", category="control", alert="Baseline.",
                                inject={}, truth={"causes": []}, checks=[])
    snapshot.capture(control_scenario, T_INJECT, T_END, NAMES, fetch=recording_fetch(), out_dir=tmp_path)

    assert calls["jaeger_raw"] and calls["os_logs"]
    assert "flagd" not in calls["jaeger_raw"]
    assert "flagd-ui" not in calls["jaeger_raw"]
    assert "load-generator" not in calls["jaeger_raw"]
    for query in calls["os_logs"]:
        assert "flagd" not in query and "flagd-ui" not in query
        assert "load-generator" not in query


def test_capture_fetches_pre_fault_and_fault_windows_per_service(tmp_path):
    """Each service is queried over [since, t_inject) and [t_inject, t_end]; each window gets the full cap."""
    since = T_INJECT - config.CAPTURE_LOOKBACK_S
    trace_calls, log_calls = [], []

    def jaeger_raw(service, start, end, limit):
        trace_calls.append((service, start, end, limit))
        return otlp_payload(service, [{"span_id": f"{service}-{start}-{i}", "name": "op"} for i in range(limit)])

    def os_logs(query, start, end, size):
        log_calls.append((query, start, end, size))
        phase = "pre" if end <= T_INJECT else "fault"
        return [{"@timestamp": "t", "resource": {"service.name": query.split('"')[1]}, "severity": {"text": "INFO", "number": 9},
                 "body": f"{phase} {start} {i}"} for i in range(size)]

    def prom_range(query, start, end, step):
        return []

    fetch = SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)
    control = Scenario(id="control-test", category="control", alert="Baseline.", inject={}, truth={"causes": []}, checks=[])
    out = snapshot.capture(control, T_INJECT, T_END, NAMES, fetch=fetch, out_dir=tmp_path)

    for service in config.APP_SERVICES:
        assert (service, since, T_INJECT, config.TRACES_PER_SERVICE) in trace_calls
        assert (service, T_INJECT, T_END, config.TRACES_PER_SERVICE) in trace_calls
    assert len(trace_calls) == 2 * len(config.APP_SERVICES)
    for service in config.KNOWN_TARGETS:
        q = f'resource.service.name:"{service}"'
        assert (q, since, T_INJECT, config.LOGS_PER_SERVICE) in log_calls
        assert (q, T_INJECT, T_END, config.LOGS_PER_SERVICE) in log_calls
    assert len(log_calls) == 2 * len(config.KNOWN_TARGETS)

    # chatty backend: cap-many items per call -> snapshot holds both windows, not just the newest
    snap = snapshot.load(out["path"])
    cart_spans = [s for s in snap["spans"] if s["service"] == "cart"]
    assert len(cart_spans) == 2 * config.TRACES_PER_SERVICE
    assert {s["span_id"].split("-")[1] for s in cart_spans} == {str(since), str(T_INJECT)}
    assert sum(l["body"].startswith("pre") for l in snap["logs"]) == len(config.KNOWN_TARGETS) * config.LOGS_PER_SERVICE
    assert sum(l["body"].startswith("fault") for l in snap["logs"]) == len(config.KNOWN_TARGETS) * config.LOGS_PER_SERVICE


def test_validate_snapshot_rescores_stored_metrics_against_changed_checks(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(prom_value_after=0.05), out_dir=tmp_path)
    assert out["valid"] is False
    path = Path(out["path"])
    meta_before = (path / "meta.json").read_bytes()

    relaxed = Scenario(**{**SCENARIO.__dict__, "checks": [{"service": "payment", "signal": "error_ratio", "at_least": 0.04}]})
    res = snapshot.validate_snapshot(path, relaxed, NAMES)
    assert res["valid"] is True and res["leaks"] == {} and res["results"][0]["passed"] is True
    assert json.loads((path / "validation.json").read_text(encoding="utf-8")) == res
    assert (path / "meta.json").read_bytes() == meta_before

    res = snapshot.validate_snapshot(path, SCENARIO, NAMES)  # original threshold fails again
    assert res["valid"] is False
    assert json.loads((path / "validation.json").read_text(encoding="utf-8"))["valid"] is False


def test_resanitize_keeps_legacy_flag_key_spans_and_strips_the_key(tmp_path):
    spans = [flat_span(span_id="legacy", attrs={"demo.[redacted].recommendation_cache": True, "demo.product.count": 10}),
             flat_span(span_id="gone", name="router flagservice egress")]
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", spans)
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [])
    counts = snapshot.resanitize(tmp_path, NAMES)
    assert counts["spans"] == (2, 1)
    (kept,) = snapshot._read_jsonl_gz(tmp_path / "spans.jsonl.gz")
    assert kept["span_id"] == "legacy" and kept["attributes"] == {"demo.product.count": 10}


def test_resanitize_keeps_and_rewrites_legacy_product_catalog_spans(tmp_path):
    legacy = flat_span(service="frontend", span_id="pc", error=True, message="Error: Product Catalog Fail [redacted] Enabled")
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [legacy])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [])
    assert snapshot.resanitize(tmp_path, NAMES)["spans"] == (1, 1)
    (kept,) = snapshot._read_jsonl_gz(tmp_path / "spans.jsonl.gz")
    assert kept["span_id"] == "pc" and kept["message"] == "Error: Product Catalog Fail"


def test_resanitize_drops_fault_announcing_ad_log(tmp_path):
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [flat_span(span_id="a")])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [flat_log("ad", "High CPU-Load problempattern enabled"),
                                                          flat_log("ad", "served ad")])
    assert snapshot.resanitize(tmp_path, NAMES)["logs"] == (2, 1)
    assert [l["body"] for l in snapshot._read_jsonl_gz(tmp_path / "logs.jsonl.gz")] == ["served ad"]


def test_resanitize_dry_run_counts_exact_duplicate_logs_apart_from_dropped_rows(tmp_path):
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [flat_log("ad", "served ad"), flat_log("ad", "served ad"),
                                                          flat_log("ad", "problempattern on")])
    counts = snapshot.resanitize(tmp_path, NAMES, dry_run=True)
    assert counts["logs"] == (3, 1) and counts["duplicate_logs"] == 1 and len(counts["dropped"]["logs"]) == 1


def test_resanitize_drops_load_generator_span_log_and_metrics_series_and_unknown_keys(tmp_path):
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [flat_span(service="load-generator", name="user_flood_home", span_id="lg"),
                                                           flat_span(span_id="ok")])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [flat_log("load-generator", "User flooding homepage 10 times")])
    series = [[1.0, 2.0]]
    (tmp_path / "metrics.json").write_text(json.dumps(
        {"rps": {"payment": series, "load-generator": series, "grafana": series}, "mem_mb": {"kafka": series}}))
    counts = snapshot.resanitize(tmp_path, NAMES)
    assert counts["spans"] == (2, 1) and counts["logs"] == (1, 0) and counts["metrics"] == (4, 2)
    assert json.loads((tmp_path / "metrics.json").read_text()) == {"rps": {"payment": series}, "mem_mb": {"kafka": series}}
    assert [s["span_id"] for s in snapshot._read_jsonl_gz(tmp_path / "spans.jsonl.gz")] == ["ok"]
    assert sanitize.scan_snapshot(tmp_path, NAMES) == {}
    before = (tmp_path / "metrics.json").read_bytes()
    assert snapshot.resanitize(tmp_path, NAMES)["metrics"] == (2, 2) and (tmp_path / "metrics.json").read_bytes() == before


def test_resanitize_dry_run_leaves_metrics_alone(tmp_path):
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [])
    text = json.dumps({"rps": {"load-generator": [[1.0, 2.0]]}})
    (tmp_path / "metrics.json").write_text(text)
    assert snapshot.resanitize(tmp_path, NAMES, dry_run=True)["metrics"] == (1, 0)
    assert (tmp_path / "metrics.json").read_text() == text


def test_resanitize_removes_stale_tmp_files_and_never_promotes_them(tmp_path):
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [flat_span(span_id="ok")])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [])
    good = json.dumps({"rps": {"payment": [[1.0, 2.0]]}})
    (tmp_path / "metrics.json").write_text(good)
    for n in ("metrics.json.tmp", "spans.jsonl.gz.tmp", "logs.jsonl.gz.tmp"):
        (tmp_path / n).write_text("junk")
    assert snapshot.resanitize(tmp_path, NAMES)["metrics"] == (1, 1)
    assert (tmp_path / "metrics.json").read_text() == good
    assert sorted(p.name for p in tmp_path.iterdir()) == ["logs.jsonl.gz", "metrics.json", "spans.jsonl.gz"]


# --- latest_rows: newest index row per scenario, rows without a path skipped ---

def test_latest_rows_newest_row_with_a_path_wins(tmp_path):
    index = tmp_path / "index.jsonl"
    rows = [{"scenario": "a", "path": "p1", "valid": False},
            {"scenario": "b", "path": "q1", "valid": True},
            {"scenario": "a", "path": "p2", "valid": True},
            {"scenario": "a", "valid": False, "error": "capture failed"},   # no path: skipped, p2 stays latest
            {"scenario": "c", "valid": False, "error": "never captured"}]   # only pathless rows: absent
    index.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n", encoding="utf-8")
    assert snapshot.latest_rows(index) == {"a": rows[2], "b": rows[1]}
    assert snapshot.latest_rows(index, ["b", "zzz"]) == {"b": rows[1]}
    assert snapshot.latest_rows(tmp_path / "missing.jsonl") == {}


# --- log capture: exact service match, exact duplicates removed ---

def _os_row(service, body, ts="t1"):
    return {"@timestamp": ts, "resource": {"service.name": service}, "severity": {"text": "INFO", "number": 9},
            "body": body}


def test_capture_logs_keep_only_the_queried_service_and_drop_exact_duplicates(tmp_path):
    fetch = fake_fetch()

    def os_logs(query, start, end, size):
        if start < T_INJECT:  # pre-fault window: nothing
            return []
        if query == 'resource.service.name:"frontend"':  # the query also matches frontend-proxy
            return [_os_row("frontend", "GET /"), _os_row("frontend-proxy", "proxied GET /")]
        if query == 'resource.service.name:"recommendation"':  # emitted twice
            return [_os_row("recommendation", "rec ok")] * 2 + [_os_row("recommendation", "rec ok", ts="t2")]
        return []

    fetch.os_logs = os_logs
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fetch, out_dir=tmp_path)
    logs = snapshot.load(out["path"])["logs"]
    assert sorted((l["service"], l["body"], l["ts"]) for l in logs) == [
        ("frontend", "GET /", "t1"), ("recommendation", "rec ok", "t1"), ("recommendation", "rec ok", "t2")]
    # frontend-proxy keeps its own logs when queried as itself
    fetch.os_logs = lambda q, s, e, n: [_os_row("frontend-proxy", "own")] if q.endswith('"frontend-proxy"') and s >= T_INJECT else []
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fetch, out_dir=tmp_path / "again")
    assert [l["service"] for l in snapshot.load(out["path"])["logs"]] == ["frontend-proxy"]


def test_resanitize_drops_exact_duplicate_logs_only(tmp_path):
    a, b = flat_log("cart", "same", "t1"), flat_log("cart", "same", "t2")
    snapshot._write_jsonl_gz(tmp_path / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(tmp_path / "logs.jsonl.gz", [a, dict(a), b, dict(b, severity="ERROR")])
    counts = snapshot.resanitize(tmp_path, NAMES)
    assert counts["logs"] == (4, 3)
    assert snapshot._read_jsonl_gz(tmp_path / "logs.jsonl.gz") == [a, b, dict(b, severity="ERROR")]

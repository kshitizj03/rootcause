import json
from pathlib import Path
from types import SimpleNamespace

from helpers import FLAGS, otlp_payload
from rootcause import sanitize, snapshot
from rootcause.scenarios import Scenario

NAMES = sanitize.flag_names(FLAGS)
T_INJECT, T_END = 100_000.0, 100_180.0
SCENARIO = Scenario(id="payment-test", category="easy", alert="Some orders fail at checkout.",
                    inject={"flags": {"paymentFailure": "50%"}},
                    truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]},
                    checks=[{"service": "payment", "signal": "error_ratio", "at_least": 0.2}])


def fake_fetch(prom_value_after=0.5, t_inject=T_INJECT):
    """Every series is 0 before t_inject and prom_value_after from then on."""
    def prom_range(query, start, end, step):
        vals = [[t, str(prom_value_after) if t >= t_inject else "0"] for t in range(int(start), int(end) + 1, step)]
        return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": vals}]

    def jaeger_raw(service, start, end, limit):
        if service != "payment":
            return {"result": {"resourceSpans": []}}
        return otlp_payload("payment", [
            {"span_id": "a", "name": "charge", "error": True, "message": "Invalid token",
             "events": [("feature_flag.evaluation", {"feature_flag.key": "paymentFailure"})]},
            {"span_id": "b", "name": "flag lookup", "attrs": {"url.full": "http://flagd:8013/x"}},
        ])

    def os_logs(query, start, end, size):
        if '"payment"' not in query:
            return []
        return [{"@timestamp": "t", "resource": {"service.name": "payment"},
                 "severity": {"text": "ERROR", "number": 17}, "body": "Payment request failed. Invalid token."},
                {"@timestamp": "t", "resource": {"service.name": "payment"},
                 "severity": {"text": "INFO", "number": 9}, "body": "FeatureFlag 'paymentFailure' is activated"}]

    return SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)


def test_capture_writes_sanitised_valid_snapshot(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(), out_dir=tmp_path, demo_commit="abc")
    path = Path(out["path"])
    assert out["valid"] is True and out["leaks"] == {}
    for name in ("meta.json", "truth.json", "metrics.json", "spans.jsonl.gz", "logs.jsonl.gz", "validation.json"):
        assert (path / name).exists(), name
    snap = snapshot.load(path)
    assert snap["meta"]["fault_start"] == T_INJECT and snap["meta"]["demo_commit"] == "abc"
    assert "truth" not in snap
    assert [s["span_id"] for s in snap["spans"]] == ["a"]
    assert snap["spans"][0]["events"] == []
    assert any("[redacted]" in l["body"] for l in snap["logs"])
    assert snapshot.load_truth(path) == SCENARIO.truth
    assert json.loads((path / "validation.json").read_text())["valid"] is True


def test_capture_marks_invalid_when_signal_is_too_weak(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(prom_value_after=0.05), out_dir=tmp_path)
    assert out["valid"] is False
    assert out["results"][0]["passed"] is False


def test_capture_empty_spans_and_logs(tmp_path):
    """Empty spans/logs (e.g. control scenarios) still write all three tool files; validation runs cleanly."""
    def empty_fetch():
        def prom_range(query, start, end, step):
            vals = [[t, "0"] for t in range(int(start), int(end) + 1, step)]
            return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": vals}]

        def jaeger_raw(service, start, end, limit):
            return {"result": {"resourceSpans": []}}

        def os_logs(query, start, end, size):
            return []

        return SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)

    control_scenario = Scenario(id="control-test", category="control", alert="Baseline with no faults.",
                                inject={}, truth={"causes": []},
                                checks=[])
    out = snapshot.capture(control_scenario, T_INJECT, T_END, NAMES, fetch=empty_fetch(), out_dir=tmp_path)
    path = Path(out["path"])

    # All tool files written, even when empty
    assert (path / "spans.jsonl.gz").exists()
    assert (path / "logs.jsonl.gz").exists()

    snap = snapshot.load(path)
    assert snap["spans"] == []
    assert snap["logs"] == []

    # Validation runs cleanly with no leaks
    assert out["leaks"] == {}
    validation = json.loads((path / "validation.json").read_text())
    assert validation["leaks"] == {}

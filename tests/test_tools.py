import inspect
import json

from rootcause import tools

T0 = 1000.0
SNAP = {
    "meta": {"alert": "a", "baseline_start": T0 - 900, "fault_start": T0, "end": T0 + 300},
    "metrics": {"error_ratio": {"payment": [[T0 - 60 + 15 * i, 0.1234567 * i] for i in range(12)]},
                "mem_mb": {"kafka": [[T0, 600.0]]}},
    "spans": [
        {"trace_id": "t1", "span_id": "a", "parent_id": "", "service": "frontend", "name": "GET /cart",
         "start_ms": (T0 + 5) * 1000, "dur_ms": 900.0, "error": True, "message": "upstream failed",
         "attributes": {}, "events": []},
        {"trace_id": "t1", "span_id": "b", "parent_id": "a", "service": "payment", "name": "charge",
         "start_ms": (T0 + 6) * 1000, "dur_ms": 800.0, "error": True, "message": "Invalid token",
         "attributes": {}, "events": []},
        {"trace_id": "t2", "span_id": "c", "parent_id": "", "service": "payment", "name": "charge",
         "start_ms": (T0 - 100) * 1000, "dur_ms": 20.0, "error": False, "message": "",
         "attributes": {}, "events": []},
    ],
    "logs": [
        {"ts": "1970-01-01T00:16:50.000Z", "service": "payment", "severity": "ERROR", "severity_number": 17,
         "body": "Payment request failed. Invalid token.", "trace_id": "t1"},
        {"ts": "1970-01-01T00:15:00.5Z", "service": "payment", "severity": "INFO", "severity_number": 9,
         "body": "charged ok", "trace_id": "t2"},
    ],
}


def out(name, args):
    return json.loads(tools.call(SNAP, name, args))


def test_list_services_unions_metrics_spans_and_logs():
    assert out("list_services", {}) == {"services": ["frontend", "kafka", "payment"]}


def test_get_metric_thins_to_one_point_per_minute_relative_to_alert():
    r = out("get_metric", {"service": "payment", "signal": "error_ratio"})
    assert r["points"][0] == [-60, 0.0] and r["points"][1][0] == 0 and len(r["points"]) == 3
    assert r["points"][1][1] == 0.4938  # 4 significant figures


def test_unknown_names_return_valid_options():
    assert "payment" in out("get_metric", {"service": "nope", "signal": "error_ratio"})["valid_services"]
    assert "p95_ms" in out("get_metric", {"service": "payment", "signal": "nope"})["valid_signals"]
    assert "search_logs" in out("nope", {})["valid_tools"]


def test_search_traces_summarises_errors_and_slowest():
    r = out("search_traces", {"service": "payment", "errors_only": True})
    assert r["spans_found"] == 1 and r["slowest"][0]["trace_id"] == "t1"
    assert r["error_messages"] == {"Invalid token": 1}


def test_get_trace_orders_spans_by_start():
    r = out("get_trace", {"trace_id": "t1"})
    assert [s["service"] for s in r["spans"]] == ["frontend", "payment"] and r["spans"][0]["t"] == 5


def test_search_logs_filters_text_and_severity():
    r = out("search_logs", {"service": "payment", "text": "INVALID", "min_severity": 17})
    assert r["total"] == 1 and r["samples"][0]["t"] == 10 and "Invalid token" in r["samples"][0]["body"]


def test_epoch_handles_real_log_timestamp_shapes():
    assert tools._epoch("1970-01-01T00:16:50Z") == 1010.0
    assert tools._epoch("1970-01-01T00:16:50.5Z") == 1010.5
    assert tools._epoch("1970-01-01T00:16:50.584123456Z") == 1010.584123456  # 9-digit fraction
    assert abs(tools._epoch("2026-10-06T21:17:54.584123456Z") - tools._epoch("2026-10-06T21:17:54Z") - 0.584123456) < 1e-3


def test_bad_arguments_never_raise():
    assert "error" in out("get_metric", "{not json")
    assert "error" in out("search_traces", {"service": "payment", "limit": "many"})
    assert "error" in out("get_trace", {})
    assert "error" in out("search_logs", {"service": "payment", "limit": 1e999})  # OverflowError path
    assert "error" in out("get_trace", [1, 2])


def test_outputs_are_capped():
    big = dict(SNAP, logs=[dict(SNAP["logs"][0], body="x" * 500) for _ in range(500)])
    text = tools.call(big, "search_logs", {"service": "payment", "limit": 500})
    assert len(text) <= tools.MAX_TOOL_CHARS


def test_schemas_cover_every_tool():
    assert {s["function"]["name"] for s in tools.SCHEMAS} == set(tools.TOOLS)


def test_tools_never_touch_answer_files():
    src = inspect.getsource(tools)
    assert "truth" not in src and "validation" not in src and "index.jsonl" not in src

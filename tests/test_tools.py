import inspect
import json

import pytest

from rootcause import tools_v0 as tools

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
    assert tools.epoch("1970-01-01T00:16:50Z") == 1010.0
    assert tools.epoch("1970-01-01T00:16:50.5Z") == 1010.5
    assert tools.epoch("1970-01-01T00:16:50.584123456Z") == 1010.584123456  # 9-digit fraction
    assert abs(tools.epoch("2026-10-06T21:17:54.584123456Z") - tools.epoch("2026-10-06T21:17:54Z") - 0.584123456) < 1e-3


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


# --- cleanup: time windows, text=None, coercions, schema, never-raises ---

def spread_logs(n, severity=None):
    return [{"ts": f"1970-01-01T00:{(1000 + i) // 60:02d}:{(1000 + i) % 60:02d}.000Z", "service": "payment", "severity": "INFO",
             "severity_number": severity, "body": f"line {i}", "trace_id": ""} for i in range(n)]


def test_search_logs_time_window_is_inclusive_and_keeps_order():
    r = out("search_logs", {"service": "payment", "since": 0})
    assert [s["t"] for s in r["samples"]] == [10] and r["total"] == 1
    r = out("search_logs", {"service": "payment", "until": -50})
    assert [s["t"] for s in r["samples"]] == [-100]  # the INFO line at t=-99.5 (rounded)
    r = out("search_logs", {"service": "payment", "since": -99.5, "until": 10})  # floats; both ends inclusive
    assert r["total"] == 2 and [s["t"] for s in r["samples"]] == sorted(s["t"] for s in r["samples"])


def test_search_logs_returns_last_limit_of_the_filtered_window():
    snap = dict(SNAP, logs=spread_logs(100))  # t = 0..99
    r = json.loads(tools.call(snap, "search_logs", {"service": "payment", "since": 10, "until": 60, "limit": 5}))
    assert r["total"] == 51 and [s["t"] for s in r["samples"]] == [56, 57, 58, 59, 60]


def test_search_logs_null_severity_lines_only_appear_at_min_severity_0():
    snap = dict(SNAP, logs=spread_logs(3, severity=None))
    assert json.loads(tools.call(snap, "search_logs", {"service": "payment"}))["total"] == 3
    assert json.loads(tools.call(snap, "search_logs", {"service": "payment", "min_severity": 13}))["total"] == 0


def test_search_traces_time_window():
    assert out("search_traces", {"service": "payment", "since": 0})["spans_found"] == 1
    r = out("search_traces", {"service": "payment", "until": -50})
    assert r["spans_found"] == 1 and r["slowest"][0]["trace_id"] == "t2"
    assert out("search_traces", {"service": "payment", "since": 6, "until": 6})["spans_found"] == 1  # inclusive
    assert out("search_traces", {"service": "payment", "since": 7})["spans_found"] == 0


def test_text_none_means_no_filter():
    assert out("search_logs", {"service": "payment", "text": None})["total"] == 2


def test_errors_only_string_is_coerced():
    assert out("search_traces", {"service": "payment", "errors_only": "false"})["spans_found"] == 2
    assert out("search_traces", {"service": "payment", "errors_only": "true"})["spans_found"] == 1
    assert out("search_traces", {"service": "payment", "errors_only": "False"})["spans_found"] == 2


@pytest.mark.parametrize("limit,expected", [(0, 1), (-5, 1), (1000, 200), (3, 3)])
def test_limit_is_clamped_to_1_200(limit, expected):
    snap = dict(SNAP, logs=spread_logs(300))
    assert len(tools.search_logs(snap, "payment", limit=limit)["samples"]) == expected


@pytest.mark.parametrize("limit", [0, -5])
def test_search_traces_limit_below_one_still_returns_one_span(limit):
    assert len(tools.search_traces(SNAP, "payment", limit=limit)["slowest"]) == 1


def test_call_never_raises_for_odd_tool_names_or_unserialisable_output(monkeypatch):
    for name in (None, ["x"], {"a": 1}, 7):
        assert "error" in json.loads(tools.call(SNAP, name, {}))
    monkeypatch.setitem(tools.TOOLS, "weird", lambda snap: {"x": object()})
    assert "error" in json.loads(tools.call(SNAP, "weird", {}))


def test_truncation_marker_says_how_to_narrow():
    big = dict(SNAP, logs=[dict(SNAP["logs"][0], body="x" * 500) for _ in range(500)])
    text = tools.call(big, "search_logs", {"service": "payment", "limit": 200})
    assert text.endswith("[truncated: reduce limit or add a text/time filter]") and len(text) <= tools.MAX_TOOL_CHARS


def test_schemas_describe_windows_and_severity_numbers():
    by_name = {s["function"]["name"]: s["function"] for s in tools.SCHEMAS}
    for name in ("search_logs", "search_traces"):
        props = by_name[name]["parameters"]["properties"]
        assert props["since"]["type"] == "number" and props["until"]["type"] == "number"
    desc = by_name["search_logs"]["description"]
    assert "17 = ERROR" in desc and "13 = WARN" in desc and "9 = INFO" in desc and "no severity" in desc


def test_explicit_nulls_for_optional_arguments_use_defaults():
    r = out("search_logs", {"service": "payment", "limit": None, "min_severity": None, "text": None})
    assert r["total"] == 2
    r = out("search_traces", {"service": "payment", "limit": None})
    assert r["spans_found"] == 2

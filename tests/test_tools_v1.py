import json

from helpers import series
from rootcause import tools_v0 as tools, tools_v1

T0 = 900.0


def span(sid, parent, service, t, error=False, trace="t1"):
    return {"trace_id": trace, "span_id": sid, "parent_id": parent, "service": service, "name": "op",
            "start_ms": (T0 + t) * 1000, "dur_ms": 5.0, "error": error, "message": "", "attributes": {}, "events": []}


SNAP = {"meta": {"alert": "a", "baseline_start": 0.0, "fault_start": T0, "end": 1200.0},
        "metrics": {"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)},
                    "rps": {"frontend": series(20.0, 40.0)},
                    "p95_ms": {"payment": series(100.0, 110.0)}},
        "spans": [span("a", "", "checkout", -50), span("b", "a", "payment", -49),
                  span("c", "", "checkout", 10, trace="t2"), span("d", "c", "payment", 11, error=True, trace="t2"),
                  span("e", "d", "payment", 12, trace="t2")],
        "logs": []}


def out(name, args=None):
    return json.loads(tools_v1.call(SNAP, name, args or {}))


def test_v0_call_unchanged_and_v1_includes_v0_tools():
    assert set(tools.TOOLS) <= set(tools_v1.TOOLS)
    assert {"top_changes", "service_health", "service_map"} <= set(tools_v1.TOOLS)
    assert {s["function"]["name"] for s in tools_v1.SCHEMAS} == set(tools_v1.TOOLS)
    assert "error" in json.loads(tools.call(SNAP, "top_changes", {}))  # v0 registry doesn't have it


def test_top_changes_ranks_and_hides_load_by_default():
    r = out("top_changes")
    assert r["changes"][0]["service"] == "payment" and r["changes"][0]["signal"] == "error_ratio"
    assert r["changes"][0]["change"] == "+30.0x" and all(c["signal"] != "rps" for c in r["changes"])
    assert any(c["signal"] == "rps" for c in out("top_changes", {"include_load": True})["changes"])


def test_service_health_lists_every_signal_and_handles_unknown():
    r = out("service_health", {"service": "payment"})
    assert {s["signal"] for s in r["signals"]} == {"error_ratio", "p95_ms"}
    assert "valid_services" in out("service_health", {"service": "nope"})


def test_service_map_counts_cross_service_edges_before_and_after():
    r = out("service_map")
    assert r["edges"] == [{"caller": "checkout", "callee": "payment", "calls_before": 1, "calls_after": 1,
                           "errors_before": 0, "errors_after": 1}]  # same-service edge d->e is not an edge


def test_change_tools_on_sparse_snapshots():
    empty = {"meta": SNAP["meta"], "metrics": {}, "spans": [], "logs": []}
    assert json.loads(tools_v1.call(empty, "top_changes", {})) ["changes"] == []
    assert json.loads(tools_v1.call(empty, "service_map", {}))["edges"] == []


def test_services_without_complete_windows_get_no_special_surfacing():
    # no "incomplete" list or note (it was shaped by viewing a held-out incident); such a service is simply absent from the summary
    late = {"error_ratio": {**SNAP["metrics"]["error_ratio"], "late": [[float(t), 0.2] for t in range(915, 1215, 15)]}}
    snap = dict(SNAP, metrics=late)
    r = json.loads(tools_v1.call(snap, "top_changes", {}))
    assert set(r) == {"changes", "note"} and "incomplete" not in r["note"] and all(c["service"] != "late" for c in r["changes"])
    h = json.loads(tools_v1.call(snap, "service_health", {"service": "late"}))
    assert "late" in h["error"] and "late" in h["valid_services"] and "signals" not in h
    snap_spans = dict(SNAP, spans=SNAP["spans"] + [span("z", "", "ghost", 1)])  # known via spans only, no metrics
    assert "error" in json.loads(tools_v1.call(snap_spans, "service_health", {"service": "ghost"}))


def test_service_map_ranks_vanished_edges_after_error_edges_before_stable_ones():
    spans = SNAP["spans"] + [span("f", "", "checkout", -30, trace="t3"), span("g", "f", "cart", -29, trace="t3"),
                             span("h", "", "checkout", 20, trace="t4"), span("i", "h", "inventory", 21, trace="t4"),
                             span("j", "", "checkout", 30, trace="t5"), span("k", "j", "inventory", 31, trace="t5"),
                             span("l", "", "checkout", -20, trace="t6"), span("m", "l", "inventory", -19, trace="t6")]
    edges = json.loads(tools_v1.call(dict(SNAP, spans=spans), "service_map", {}))["edges"]
    assert [e["callee"] for e in edges] == ["payment", "cart", "inventory"]
    assert edges[1]["stopped"] is True and "stopped" not in edges[0] and "stopped" not in edges[2]


def test_n_and_limit_are_clamped_and_include_load_accepts_strings():
    assert len(out("top_changes", {"n": 0})["changes"]) == 1 and len(out("top_changes", {"n": -5})["changes"]) == 1
    assert len(out("top_changes", {"n": 10**6, "include_load": True})["changes"]) == 4  # 4 rows exist, cap is 40
    assert len(out("service_map", {"limit": 0})["edges"]) == 1
    assert any(c["signal"] == "rps" for c in out("top_changes", {"include_load": "true"})["changes"])
    assert all(c["signal"] != "rps" for c in out("top_changes", {"include_load": "false"})["changes"])


def test_top_changes_note_uses_config_windows_and_warns_about_vanished_services():
    note = out("top_changes")["note"]
    assert "15 min before" in note and "60 s after" in note and "stopped reporting" in note


def test_service_map_ignores_spans_older_than_the_capture_window():
    old = [span("o1", "", "shipping", -9150, trace="t7"), span("o2", "o1", "quote", -9149, trace="t7")]
    edges = json.loads(tools_v1.call(dict(SNAP, spans=SNAP["spans"] + old), "service_map", {}))["edges"]
    assert [e["callee"] for e in edges] == ["payment"] and "5 min before" in out("service_map")["note"]


def test_service_map_ranks_a_stopped_edge_that_had_errors_above_stable_edges():
    spans = SNAP["spans"] + [span("f", "", "checkout", -30, trace="t3"), span("g", "f", "cart", -29, error=True, trace="t3"),
                             span("h", "", "checkout", 20, trace="t4"), span("i", "h", "inventory", 21, trace="t4")]
    edges = json.loads(tools_v1.call(dict(SNAP, spans=spans), "service_map", {}))["edges"]
    assert [e["callee"] for e in edges] == ["payment", "cart", "inventory"] and edges[1]["stopped"] is True
    assert "stopped" in next(s for s in tools_v1.SCHEMAS if s["function"]["name"] == "service_map")["function"]["description"]

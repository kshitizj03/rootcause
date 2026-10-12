import json

from rootcause import tools, tools_v1

T0 = 900.0


def series(base, fault):
    return [[float(t), base] for t in range(0, 901, 15)] + [[float(t), fault] for t in range(915, 1215, 15)]


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

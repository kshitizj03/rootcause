import pytest

from helpers import META, series, snap
from rootcause import signals, summary

def test_windows_skip_the_ramp():
    assert summary.windows(META) == ((0.0, 900.0), (960.0, 1200.0))


def test_changes_rank_relative_rise_with_floors():
    rows = summary.changes(snap({"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)},
                                 "p95_ms": {"checkout": series(100.0, 150.0)}}))
    top = rows[0]
    assert (top["service"], top["signal"], top["direction"], top["fault_type"]) == ("payment", "error_ratio", "up", "errors")
    assert abs(top["score"] - 0.3 / 0.01) < 1e-9          # baseline 0 -> divided by the 0.01 floor
    checkout = next(r for r in rows if r["service"] == "checkout")
    assert abs(checkout["score"] - 0.5) < 1e-9


def test_memory_uses_the_window_peak():
    pts = series(60.0, 60.0)
    pts[-5][1] = 500.0  # one sawtooth peak inside the fault window
    row = summary.changes(snap({"mem_mb": {"recommendation": pts}}))[0]
    assert row["value"] == 500.0 and row["fault_type"] == "resource"


def test_uptime_becomes_restarts():
    up = [[float(t), float(t)] for t in range(0, 1080, 15)] + [[1080.0, 5.0], [1095.0, 20.0]]
    row = summary.changes(snap({"uptime_s": {"email": up}}))[0]
    assert (row["signal"], row["value"], row["baseline"]) == ("restarts", 1, 0)


def test_services_without_data_in_a_window_are_skipped():
    late = [[float(t), 1.0] for t in range(960, 1215, 15)]  # no baseline points
    assert summary.changes(snap({"cpu_cores": {"ad": late}, "rps": {"cart": []}})) == []


def test_rps_rows_have_no_fault_type():
    row = summary.changes(snap({"rps": {"frontend": series(20.0, 40.0)}}))[0]
    assert row["fault_type"] is None and row["direction"] == "up"


def test_point_exactly_at_fault_start_counts_toward_the_baseline():
    # Same window semantics as signals.window_stat: the sample at t=fault_start is in the baseline (0..900 inclusive)
    pts = [[float(t), 0.0] for t in range(0, 900, 15)] + [[900.0, 0.3]] + [[float(t), 0.3] for t in range(915, 1215, 15)]
    row = summary.changes(snap({"error_ratio": {"payment": pts}}))[0]
    assert row["baseline"] == signals.window_stat(pts, 0.0, 900.0)
    assert row["baseline"] == pytest.approx(0.3 / 61)

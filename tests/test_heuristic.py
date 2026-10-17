from helpers import series, snap
from rootcause import heuristic
from rootcause.score import Cause

def test_names_the_service_whose_fault_signal_rose_most():
    r = heuristic.diagnose(snap({"error_ratio": {"payment": series(0.0, 0.3), "checkout": series(0.0, 0.05)},
                                 "p95_ms": {"frontend": series(100.0, 130.0)}}))
    assert r.verdict == "incident"
    assert r.causes == (Cause("payment", "errors"), Cause("checkout", "errors"))
    assert 0.9 < r.confidence < 1.0
    assert r.evidence[0]["kind"] == "metric" and r.evidence[0]["service"] == "payment" and r.evidence[0]["signal"] == "error_ratio"


def test_traffic_and_falling_signals_are_ignored():
    r = heuristic.diagnose(snap({"rps": {"frontend": series(20.0, 80.0)},
                                 "p95_ms": {"cart": series(100.0, 10.0)}}))
    assert r.verdict == "no_incident" and r.causes == ()


def test_below_threshold_is_no_incident():
    r = heuristic.diagnose(snap({"cpu_cores": {"ad": series(0.10, 0.18)}}))  # +80% < doubled
    assert r.verdict == "no_incident" and r.confidence == 0.5


def test_exactly_doubled_counts_as_an_incident():
    # score exactly 1.0 = THRESHOLD: the rule is inclusive (>=), and the baseline every agent is compared with depends on it
    assert heuristic.THRESHOLD == 1.0
    assert heuristic.diagnose(snap({"p95_ms": {"cart": series(100.0, 200.0)}})).verdict == "incident"


def test_at_most_three_distinct_services():
    m = {"error_ratio": {s: series(0.0, 0.1 * (i + 1)) for i, s in enumerate(["a", "b", "c", "d"])},
         "p95_ms": {"d": series(10.0, 1000.0)}}
    r = heuristic.diagnose(snap(m))
    assert [c.service for c in r.causes] == ["d", "c", "b"]


def test_solve_returns_report_and_info():
    report, info = heuristic.solve(snap({}))
    assert report.verdict == "no_incident" and info == {"solver": "heuristic"}

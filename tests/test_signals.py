from rootcause import signals

BASE, FAULT = (0, 100), (200, 300)


def series(before, after):
    return [[t, before] for t in range(0, 101, 20)] + [[t, after] for t in range(200, 301, 20)]


def test_window_stat_mean_max_and_empty():
    pts = [[0, 1.0], [10, 3.0], [20, 5.0]]
    assert signals.window_stat(pts, 0, 10) == 2.0
    assert signals.window_stat(pts, 0, 20, "max") == 5.0
    assert signals.window_stat(pts, 50, 60) is None


def test_restarts_counts_uptime_drops():
    pts = [[0, 100], [10, 110], [20, 5], [30, 15], [40, 2]]
    assert signals.restarts(pts, 0, 40) == 2
    assert signals.restarts(pts, 0, 10) == 0
    assert signals.restarts(pts, 30, 40) == 1  # drop at window start counts
    assert signals.restarts(pts, 20, 40) == 2  # drop exactly at start + drop before end
    assert signals.restarts(pts, 100, 150) is None  # no in-window points


def test_window_end_tolerates_one_second_of_float_error():
    pts = [[0, 1.0], [10, 3.0], [10.9, 5.0], [11.5, 100.0]]
    assert signals.window_stat(pts, 0, 10, "max") == 5.0  # 10.9 is within EDGE_TOLERANCE_S of the end; 11.5 is not
    assert signals.window_stat([[100.000001, 7.0]], 0, 100) == 7.0


def test_restarts_include_a_drop_within_tolerance_of_the_window_end():
    assert signals.restarts([[0, 100], [10, 110], [10.5, 3]], 0, 10) == 1
    assert signals.restarts([[0, 100], [10, 110], [12, 3]], 0, 10) == 0


def test_evaluate_absolute_ratio_and_star_checks():
    metrics = {"error_ratio": {"payment": series(0.0, 0.5), "cart": series(0.0, 0.0)},
               "p95_ms": {"product-catalog": series(10, 45)}}
    checks = [{"service": "payment", "signal": "error_ratio", "at_least": 0.2},
              {"service": "product-catalog", "signal": "p95_ms", "ratio_at_least": 4},
              {"service": "*", "signal": "error_ratio", "at_most": 0.1}]
    res = signals.evaluate(checks, metrics, BASE, FAULT)
    by = {(r["target"], r["signal"], "at_most" in r): r["passed"] for r in res}
    assert by[("payment", "error_ratio", False)] is True
    assert by[("product-catalog", "p95_ms", False)] is True        # 45 / 10 = 4.5
    assert by[("payment", "error_ratio", True)] is False           # 0.5 > 0.1
    assert by[("cart", "error_ratio", True)] is True


def test_ratio_uses_floor_when_baseline_is_zero():
    metrics = {"error_ratio": {"cart": series(0.0, 0.031)}}
    res = signals.evaluate([{"service": "cart", "signal": "error_ratio", "ratio_at_least": 3}], metrics, BASE, FAULT)
    assert res[0]["passed"] is True                                # 0.031 / floor 0.01 = 3.1


def test_missing_data_fails_with_reason():
    res = signals.evaluate([{"service": "email", "signal": "mem_mb", "stat": "max", "ratio_at_least": 2}], {}, BASE, FAULT)
    assert res[0]["passed"] is False and res[0]["reason"] == "no data"


def test_restarts_check_uses_uptime_series():
    metrics = {"uptime_s": {"recommendation": [[0, 100], [100, 200], [220, 5], [260, 40], [280, 3]]}}
    res = signals.evaluate([{"service": "recommendation", "signal": "restarts", "at_least": 1}], metrics, BASE, FAULT)
    assert res[0]["passed"] is True and res[0]["value"] == 2


def test_fetch_series_filters_hidden_unknown_and_nan():
    def prom_range(query, start, end, step):
        return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": [[1, "0.5"], [2, "NaN"]]},
                {"metric": {"service_name": "flagd", "container_name": "flagd"}, "values": [[1, "1"]]},
                {"metric": {"service_name": "load-generator", "container_name": "load-generator"}, "values": [[1, "1"]]},
                {"metric": {"service_name": "grafana", "container_name": "grafana"}, "values": [[1, "1"]]}]
    out = signals.fetch_series(prom_range, 0, 10, 5)
    assert set(out) == set(signals.SIGNALS)
    assert out["rps"] == {"payment": [[1.0, 0.5]]}
    assert out["mem_mb"] == {"payment": [[1.0, 0.5]]}


def test_wildcard_empty_source_fails_with_reason():
    res = signals.evaluate([{"service": "*", "signal": "error_ratio", "at_most": 0.1}], {}, BASE, FAULT)
    assert len(res) == 1
    assert res[0]["target"] == "*"
    assert res[0]["passed"] is False
    assert res[0]["reason"] == "no data"


def test_restarts_check_without_fault_window_points_fails_with_no_data():
    metrics = {"uptime_s": {"app": [[0, 100], [10, 110], [20, 5]]}}
    res = signals.evaluate([{"service": "app", "signal": "restarts", "at_most": 0}], metrics, BASE, FAULT)
    assert res[0]["passed"] is False and res[0]["reason"] == "no data"


def test_ratio_at_least_with_no_baseline_fails():
    # Series with no data in baseline window [0, 100] but data in fault window [200, 300]
    metrics = {"rps": {"web": [[200, 0.5], [220, 0.5], [240, 0.5]]}}
    res = signals.evaluate([{"service": "web", "signal": "rps", "ratio_at_least": 2}], metrics, BASE, FAULT)
    assert res[0]["passed"] is False and res[0]["reason"] == "no baseline"

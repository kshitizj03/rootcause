from rootcause import evidence
from rootcause.score import Report, make_report

T0 = 900.0


def series(base, fault):
    return [[float(t), base] for t in range(0, 901, 15)] + [[float(t), fault] for t in range(915, 1215, 15)]


SNAP = {"meta": {"alert": "a", "baseline_start": 0.0, "fault_start": T0, "end": 1200.0},
        "metrics": {"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)}},
        "spans": [{"trace_id": "abc", "span_id": "s", "parent_id": "", "service": "payment", "name": "charge",
                   "start_ms": 910000.0, "dur_ms": 5.0, "error": True, "message": "", "attributes": {}, "events": []}],
        "logs": [{"ts": "1970-01-01T00:15:20Z", "service": "payment", "severity": "WARN", "severity_number": 13,
                  "body": "Payment request failed.   Invalid token.", "trace_id": "abc"}]}


def report(*items):
    return make_report({"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                        "evidence": list(items), "confidence": 0.5})


def test_normalisation_keeps_strings_and_never_raises():
    r = report("plain words", {"kind": "metric", "service": "Payment", "signal": "error_ratio", "claim": "up"},
               {"kind": "weird"}, {"kind": "log"}, 42, None)
    assert r.evidence[0] == "plain words"
    assert r.evidence[1] == {"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "up"}
    assert all(e["kind"] == "text" for e in r.evidence[2:4])


def test_each_kind_is_checked_against_the_snapshot():
    r = report({"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "0 -> 0.3"},
               {"kind": "metric", "service": "cart", "signal": "error_ratio", "claim": "flat"},
               {"kind": "trace", "trace_id": "abc", "service": "payment", "claim": "error span"},
               {"kind": "trace", "trace_id": "abc", "service": "cart", "claim": "wrong service"},
               {"kind": "trace", "trace_id": "zzz", "claim": "made up"},
               {"kind": "log", "service": "payment", "quote": "request failed. invalid TOKEN"},
               {"kind": "log", "service": "payment", "quote": "failed"},
               "free text")
    c = evidence.check(r, SNAP)
    assert [i["grounded"] for i in c["items"]] == [True, False, True, False, False, True, False, False]
    assert c["grounded"] == 3 and c["total"] == 8


def test_empty_evidence():
    assert evidence.check(Report("no_incident"), SNAP) == {"items": [], "grounded": 0, "distinctive": 0, "total": 0}


def mk(*items):
    return make_report({"verdict": "no_incident", "evidence": list(items)})


def test_normalisation_survives_odd_shapes():
    assert [e["kind"] for e in mk({"kind": ["x"]}, {"kind": {}}, {"kind": None}).evidence] == ["text"] * 3
    assert make_report({"verdict": "no_incident", "evidence": 5}).evidence == ({"kind": "text", "text": "5"},)
    r = make_report({"verdict": "no_incident",
                     "evidence": {"kind": "metric", "service": "a", "signal": "rps", "claim": "c"}})
    assert r.evidence == ({"kind": "metric", "service": "a", "signal": "rps", "claim": "c"},)
    assert mk({"kind": " Metric ", "service": "a", "signal": "rps"}).evidence[0]["kind"] == "metric"
    assert mk({"kind": "trace", "trace_id": "t", "service": 5}).evidence[0]["kind"] == "text"
    assert mk({"kind": "trace", "trace_id": "t"}).evidence[0]["service"] is None


def test_evidence_is_capped_in_count_and_text_length():
    assert len(mk(*["x"] * 50).evidence) == 20
    e = mk({"kind": "log", "service": "a", "quote": "q" * 900}, {"kind": "metric", "service": "a", "signal": "rps",
                                                                  "claim": "c" * 900}).evidence
    assert len(e[0]["quote"]) == 500 and len(e[1]["claim"]) == 500


def test_citations_must_fall_inside_the_incident_window():
    snap = {**SNAP,
            "spans": SNAP["spans"] + [{**SNAP["spans"][0], "trace_id": "old", "start_ms": 100000.0}],
            "logs": SNAP["logs"] + [{**SNAP["logs"][0], "ts": "1970-01-01T00:05:00Z", "body": "baseline only line"},
                                    {**SNAP["logs"][0], "service": "cart", "body": "only cart says this"}]}
    r = report({"kind": "log", "service": "payment", "quote": "baseline only line"},
               {"kind": "trace", "trace_id": "old", "service": "payment"},
               {"kind": "log", "service": "payment", "quote": "only cart says this"})
    assert [i["grounded"] for i in evidence.check(r, snap)["items"]] == [False, False, False]


def test_restarts_citation_is_grounded_by_an_uptime_drop():
    up = [[float(t), float(t)] for t in range(0, 1080, 15)] + [[1080.0, 5.0], [1095.0, 20.0]]
    snap = {**SNAP, "metrics": {"uptime_s": {"email": up}}}
    r = report({"kind": "metric", "service": "email", "signal": "restarts", "claim": "restarted"})
    assert evidence.check(r, snap)["grounded"] == 1


def test_heuristic_evidence_is_all_grounded():
    from rootcause import heuristic
    r = heuristic.diagnose(SNAP)
    c = evidence.check(r, SNAP)
    assert c["total"] >= 1 and c["grounded"] == c["total"]


def _log(ts, body, service="payment"):
    return {**SNAP["logs"][0], "service": service, "ts": ts, "body": body}


def _span(trace_id, start_s, dur, error=False, service="payment"):
    return {**SNAP["spans"][0], "trace_id": trace_id, "start_ms": start_s * 1000.0, "dur_ms": dur,
            "error": error, "service": service}


DSNAP = {**SNAP,
         "logs": [_log("1970-01-01T00:05:00Z", "common word here"), _log("1970-01-01T00:15:20Z", "common word here"),
                  _log("1970-01-01T00:15:30Z", "a brand new thing"), _log("garbage", "only in a bad line"),
                  _log("1970-01-01T00:05:00Z", "hello from cart", "cart"),
                  _log("1970-01-01T00:15:40Z", "hello from cart", "payment")],
         "spans": [_span(f"base{i}", 100 + i, 10.0) for i in range(3)] +
                  [_span("fast", 910, 15.0), _span("slow", 910, 50.0), _span("err", 910, 5.0, error=True),
                   _span("cartonly", 910, 500.0, service="cart"), _span("pre", 100, 5.0, error=True)]}


def flags(*items):
    c = evidence.check(report(*items), DSNAP)
    return [(i["grounded"], i["distinctive"]) for i in c["items"]], c


def test_distinctive_separates_existing_from_anomalous():
    log = lambda q: {"kind": "log", "service": "payment", "quote": q}
    tr = lambda t, s="payment": {"kind": "trace", "trace_id": t, "service": s, "claim": "c"}
    got, c = flags(log("common word here"), log("a brand new thing"), log("only in a bad line"),
                   log("hello from cart"), tr("fast"), tr("slow"), tr("err"), tr("pre"), tr("cartonly", "cart"),
                   {"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "c"}, "text")
    assert got == [(True, False), (True, True), (False, False), (True, True), (True, False), (True, True),
                   (True, True), (False, False), (True, False), (True, True), (False, False)]
    assert c["distinctive"] == 5 and c["grounded"] == 8


def test_slow_rule_only_applies_with_pre_alert_spans_of_that_service():
    # cart has no pre-alert spans, so a slow cart span is grounded but only an error would make it distinctive
    got, _ = flags({"kind": "trace", "trace_id": "cartonly", "service": "cart", "claim": "c"})
    assert got == [(True, False)]

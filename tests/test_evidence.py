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
    assert evidence.check(Report("no_incident"), SNAP) == {"items": [], "grounded": 0, "total": 0}

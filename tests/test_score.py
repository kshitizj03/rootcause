import json

import pytest

from rootcause.score import Cause, Report, make_report, parse_report, report_to_dict, score

SINGLE = {"causes": [{"accept": ["payment"], "fault_type": "errors"}]}
TWO = {"causes": [{"accept": ["payment"], "fault_type": "errors"},
                  {"accept": ["recommendation"], "fault_type": "resource"}]}
CONTROL = {"causes": []}


def inc(*pairs, confidence=0.8):
    return Report("incident", tuple(Cause(s, f) for s, f in pairs), ("e",), confidence)


def test_make_report_validates_and_normalises():
    r = make_report({"verdict": "incident", "confidence": 0.7, "evidence": ["x"],
                     "causes": [{"service": " Payment ", "fault_type": "ERRORS"}]})
    assert r == Report("incident", (Cause("payment", "errors"),), ("x",), 0.7)


def test_make_report_truncates_to_three_causes_and_clamps_confidence():
    causes = [{"service": f"s{i}", "fault_type": "latency"} for i in range(5)]
    r = make_report({"verdict": "incident", "causes": causes, "confidence": 7})
    assert [c.service for c in r.causes] == ["s0", "s1", "s2"] and r.confidence == 1.0


@pytest.mark.parametrize("bad", [
    {"verdict": "maybe"},
    {"verdict": "incident", "causes": []},
    {"verdict": "incident", "causes": [{"service": "payment", "fault_type": "slow"}]},
    {"verdict": "incident", "causes": [{"service": "", "fault_type": "errors"}]},
    {"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}], "confidence": "high"},
    ["not", "a", "dict"],
])
def test_make_report_rejects_invalid(bad):
    with pytest.raises(ValueError):
        make_report(bad)


def test_non_incident_verdicts_drop_causes():
    r = make_report({"verdict": "no_incident", "causes": [{"service": "payment", "fault_type": "errors"}]})
    assert r.causes == () and r.verdict == "no_incident"


def test_parse_report_handles_fences_and_prose():
    text = 'Here is my answer:\n```json\n{"verdict": "no_incident", "confidence": 0.9}\n```\nThanks.'
    assert parse_report(text) == Report("no_incident", (), (), 0.9)


def test_parse_report_rejects_non_json():
    with pytest.raises(ValueError):
        parse_report("I think it is the payment service.")


def test_parse_report_skips_braces_in_prose_before_the_answer():
    text = 'Looking at {payment} first. {"verdict": "no_incident", "confidence": 0.9}'
    assert parse_report(text) == Report("no_incident", (), (), 0.9)


def test_parse_report_ignores_trailing_prose_with_braces():
    text = 'Answer: {"verdict": "no_incident", "confidence": 0.9} (see {notes})'
    assert parse_report(text) == Report("no_incident", (), (), 0.9)


def test_parse_report_takes_the_last_report_when_there_are_two():
    text = ('Draft: {"verdict": "incident", "causes": [{"service": "cart", "fault_type": "errors"}]}\n'
            'Final: {"verdict": "no_incident", "confidence": 0.6}')
    assert parse_report(text) == Report("no_incident", (), (), 0.6)


def test_parse_report_takes_the_last_report_in_an_array():
    text = ('[{"verdict": "incident", "causes": [{"service": "cart", "fault_type": "errors"}], "confidence": 0.4},'
            ' {"verdict": "no_incident", "confidence": 0.6}]')
    assert parse_report(text) == Report("no_incident", (), (), 0.6)


def test_parse_report_needs_an_object_with_a_verdict():
    with pytest.raises(ValueError, match="no JSON object found"):
        parse_report('{"confidence": 0.5} and {"x": 1}')


def test_service_names_are_normalised():
    for name in ("Product Catalog", "product_catalog", " product  catalog "):
        r = make_report({"verdict": "incident", "causes": [{"service": name, "fault_type": "errors"}]})
        assert r.causes == (Cause("product-catalog", "errors"),)


@pytest.mark.parametrize("service", [None, 42, ["payment"]])
def test_non_string_service_is_rejected(service):
    with pytest.raises(ValueError):
        make_report({"verdict": "incident", "causes": [{"service": service, "fault_type": "errors"}]})


def test_evidence_string_becomes_one_element_tuple():
    assert make_report({"verdict": "no_incident", "evidence": "one note"}).evidence == ("one note",)


def test_report_round_trips_through_dict():
    r = inc(("payment", "errors"))
    assert make_report(json.loads(json.dumps(report_to_dict(r)))) == r


def test_single_cause_scoring_uses_top_ranked_only():
    assert score(inc(("payment", "errors")), SINGLE)["correct"] == 1.0
    wrong_first = score(inc(("checkout", "errors"), ("payment", "errors")), SINGLE)
    assert wrong_first["correct"] == 0.0 and wrong_first["top3"] is True
    assert score(inc(("payment", "latency")), SINGLE)["fault_type_ok"] is False


def test_two_fault_partial_credit_and_distinct_matching():
    assert score(inc(("payment", "errors"), ("recommendation", "resource")), TWO)["correct"] == 1.0
    half = score(inc(("payment", "errors"), ("cart", "errors")), TWO)
    assert half["correct"] == 0.5 and half["fault_type_ok"] is False
    assert score(inc(("payment", "errors"), ("payment", "errors")), TWO)["correct"] == 0.5


def test_controls_and_false_alarms():
    ok = score(Report("no_incident"), CONTROL)
    assert ok["correct"] == 1.0 and ok["false_alarm"] is False and ok["fault_type_ok"] is None
    alarm = score(inc(("payment", "errors")), CONTROL)
    assert alarm["correct"] == 0.0 and alarm["false_alarm"] is True


def test_abstention_is_wrong_but_flagged():
    for truth in (SINGLE, CONTROL):
        s = score(Report("insufficient_evidence"), truth)
        assert s["correct"] == 0.0 and s["abstained"] is True and s["false_alarm"] is False


def test_no_incident_on_a_real_incident_is_wrong():
    s = score(Report("no_incident"), SINGLE)
    assert s["correct"] == 0.0 and s["top3"] is False and s["fault_type_ok"] is False

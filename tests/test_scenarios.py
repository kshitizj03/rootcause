from helpers import FLAGS
from rootcause import scenarios
from rootcause.inject import flag_variants

VARIANTS = flag_variants(FLAGS)


def make(**over):
    base = dict(id="x", category="easy", alert="Some orders fail at checkout.",
                inject={"flags": {"paymentFailure": "50%"}},
                truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]},
                checks=[{"service": "payment", "signal": "error_ratio", "at_least": 0.2}], settle_s=180)
    base.update(over)
    return scenarios.Scenario(**base)


def test_all_shipped_scenarios_are_valid_and_unique():
    loaded = scenarios.load_all()
    assert len(loaded) >= 20
    assert len({s.id for s in loaded}) == len(loaded)
    problems = {s.id: scenarios.validate(s, VARIANTS) for s in loaded}
    assert {k: v for k, v in problems.items() if v} == {}
    assert sum(s.category == "control" for s in loaded) >= 4


def test_valid_example_passes():
    assert scenarios.validate(make(), VARIANTS) == []


def test_alert_must_not_name_the_root_cause_or_a_flag():
    errs = scenarios.validate(make(alert="The payment service is failing"), VARIANTS)
    assert any("names root cause payment" in e for e in errs)
    errs = scenarios.validate(make(alert="paymentFailure happened"), VARIANTS)
    assert any("mentions flag" in e for e in errs)


def test_bad_flag_variant_category_signal_and_target_are_reported():
    errs = scenarios.validate(make(category="weird", inject={"flags": {"paymentFailure": "7%"}},
                                   checks=[{"service": "nope", "signal": "vibes", "at_least": 1}]), VARIANTS)
    joined = " | ".join(errs)
    for needle in ("unknown category", "no variant 7%", "unknown signal vibes", "unknown check target nope"):
        assert needle in joined


def test_controls_have_no_causes_and_incidents_need_checks():
    assert any("controls" in e for e in scenarios.validate(make(category="control"), VARIANTS))
    assert any("no signal checks" in e for e in scenarios.validate(make(checks=[]), VARIANTS))

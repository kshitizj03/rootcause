from helpers import FLAGS
from rootcause import config, scenarios
from rootcause.inject import flag_targeting_errors, flag_variants

VARIANTS = flag_variants(FLAGS)


def make(**over):
    base = dict(id="x", category="easy", alert="Some orders fail at checkout.",
                inject={"flags": {"paymentFailure": "50%"}},
                truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]},
                checks=[{"service": "payment", "signal": "error_ratio", "at_least": 0.2}], settle_s=config.SETTLE_S)
    base.update(over)
    return scenarios.Scenario(**base)


def test_all_shipped_scenarios_are_valid_and_unique():
    loaded = scenarios.load_all()
    assert len({s.id for s in loaded}) == len(loaded)
    problems = {s.id: scenarios.validate(s, VARIANTS, flag_targeting_errors(FLAGS)) for s in loaded}
    assert {k: v for k, v in problems.items() if v} == {}


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


def test_rejection_rules():
    """Negative tests for all rejection rules."""
    # cpus action without value
    errs = scenarios.validate(make(inject={"docker": [{"action": "cpus", "container": "currency"}]}), VARIANTS)
    assert any("value" in e for e in errs), f"Expected value error, got: {errs}"

    # unknown docker action
    errs = scenarios.validate(make(inject={"docker": [{"action": "reboot", "container": "currency"}]}), VARIANTS)
    assert any("unknown docker action" in e for e in errs), f"Expected unknown action, got: {errs}"

    # unknown container
    errs = scenarios.validate(make(inject={"docker": [{"action": "pause", "container": "nosuchcontainer"}]}), VARIANTS)
    assert any("unknown container" in e for e in errs), f"Expected unknown container, got: {errs}"

    # non-control with empty causes (should have causes)
    errs = scenarios.validate(make(truth={"causes": []}), VARIANTS)
    assert any("controls" in e for e in errs), f"Expected controls error, got: {errs}"

    # bad fault_type
    errs = scenarios.validate(make(truth={"causes": [{"accept": ["payment"], "fault_type": "bugs"}]}), VARIANTS)
    assert any("unknown fault_type" in e for e in errs), f"Expected fault_type error, got: {errs}"

    # unknown truth service
    errs = scenarios.validate(make(truth={"causes": [{"accept": ["nosuchservice"], "fault_type": "errors"}]}), VARIANTS)
    assert any("unknown truth service" in e for e in errs), f"Expected truth service error, got: {errs}"

    # check missing any threshold
    errs = scenarios.validate(make(checks=[{"service": "payment", "signal": "error_ratio"}]), VARIANTS)
    assert any("threshold" in e for e in errs), f"Expected threshold error, got: {errs}"

    # mixed-case alert naming cause
    errs = scenarios.validate(make(alert="PAYMENT is down"), VARIANTS)
    assert any("names root cause" in e for e in errs), f"Expected root cause naming error, got: {errs}"

    # word boundary: mispayment should NOT match payment cause
    errs = scenarios.validate(make(alert="mispayment issue", truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]}), VARIANTS)
    assert not errs, f"Expected no errors for word boundary, got: {errs}"


def test_alert_leak_checks_spaced_and_plural_forms():
    """Alert leak checks should catch spaced/plural forms of service names."""
    # "product catalog" with cause "product-catalog" should be rejected
    errs = scenarios.validate(make(alert="product catalog is slow",
                                   truth={"causes": [{"accept": ["product-catalog"], "fault_type": "latency"}]}), VARIANTS)
    assert any("names root cause" in e for e in errs), f"Expected root cause for 'product catalog', got: {errs}"

    # "recommendations" with cause "recommendation" should be rejected
    errs = scenarios.validate(make(alert="recommendations missing",
                                   truth={"causes": [{"accept": ["recommendation"], "fault_type": "errors"}]}), VARIANTS)
    assert any("names root cause" in e for e in errs), f"Expected root cause for 'recommendations', got: {errs}"


def test_ratio_check_on_a_signal_without_a_floor_is_rejected():
    errs = scenarios.validate(make(checks=[{"service": "payment", "signal": "uptime_s", "ratio_at_least": 2}]), VARIANTS)
    assert any("ratio_at_least is not supported on uptime_s" in e for e in errs)
    assert scenarios.validate(make(checks=[{"service": "payment", "signal": "restarts", "ratio_at_least": 2}]), VARIANTS) == []


def test_validate_stat_must_be_mean_or_max():
    """Signal checks with stat must have valid value: mean or max."""
    errs = scenarios.validate(make(checks=[{"service": "payment", "signal": "p95_ms", "stat": "median", "at_least": 100}]), VARIANTS)
    assert any("stat" in e for e in errs), f"Expected stat error, got: {errs}"


def test_category_counts():
    """Verify exactly the expected number of scenarios per category."""
    loaded = scenarios.load_all()
    by_cat = {}
    for s in loaded:
        by_cat.setdefault(s.category, []).append(s.id)

    expected = {"easy": 3, "hard-cross-service": 3, "hard-silent": 6, "hard-noisy": 2, "hard-two-faults": 2, "control": 4}
    for cat, count in expected.items():
        assert len(by_cat.get(cat, [])) == count, f"Category {cat}: expected {count}, got {len(by_cat.get(cat, []))}"


def test_unsupported_targeting_is_reported_for_injected_flags_only():
    bad = {"paymentFailure": "targeting is not a simple if/then/else"}
    assert any("targeting" in e for e in scenarios.validate(make(), VARIANTS, bad))
    assert scenarios.validate(make(), VARIANTS, {"adHighCpu": "x"}) == []

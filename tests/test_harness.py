import json

import pytest

from helpers import FLAGS, Clock
from rootcause import harness, sanitize, config
from rootcause.scenarios import Scenario
from test_snapshot import SCENARIO, fake_fetch

NAMES = sanitize.flag_names(FLAGS)


class FakeInjector:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def apply(self, injection):
        self.calls.append("apply")
        if self.fail_on and self.fail_on in json.dumps(injection):
            raise RuntimeError("inject failed")

    def restore(self):
        self.calls.append("restore")


def run(tmp_path, clock, injector, scenario=SCENARIO, fetch=None):
    return harness.record(scenario, NAMES, injector, fetch=fetch or fake_fetch(t_inject=clock.t), now=clock.now,
                          sleep=clock.sleep, state_file=tmp_path / "state.json", out_dir=tmp_path / "snaps")


def failing_prom_range(*args):
    raise RuntimeError("prometheus down")


def test_record_injects_waits_captures_and_restores(tmp_path):
    clock, inj = Clock(), FakeInjector()
    out = run(tmp_path, clock, inj)
    assert inj.calls == ["apply", "restore"]
    assert clock.sleeps == [SCENARIO.settle_s]
    assert out["valid"] is True
    assert json.loads((tmp_path / "state.json").read_text())["last_restore"] == clock.t


def test_restore_happens_even_when_capture_fails(tmp_path):
    clock, inj = Clock(), FakeInjector()
    broken = fake_fetch()
    broken.prom_range = failing_prom_range
    with pytest.raises(RuntimeError, match="prometheus down"):
        run(tmp_path, clock, inj, fetch=broken)
    assert inj.calls == ["apply", "restore"]
    assert (tmp_path / "state.json").exists()


def test_cooldown_waits_for_the_remaining_time(tmp_path):
    clock = Clock()
    harness.mark_restored(clock.t - 60, tmp_path / "state.json")
    waited = harness.wait_cooldown(clock.now, clock.sleep, tmp_path / "state.json")
    assert waited == config.COOLDOWN_S - 60 and clock.sleeps == [config.COOLDOWN_S - 60]


def test_record_all_continues_after_a_failure_and_writes_index(tmp_path):
    clock = Clock()
    bad = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                   truth=SCENARIO.truth, checks=SCENARIO.checks)
    summaries = harness.record_all([bad, SCENARIO], NAMES, FakeInjector(fail_on="adFailure"), fetch=fake_fetch(t_inject=clock.t),
                                   now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                                   out_dir=tmp_path / "snaps")
    assert [s["scenario"] for s in summaries] == ["bad", "payment-test"]
    assert "inject failed" in summaries[0]["error"]
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 2

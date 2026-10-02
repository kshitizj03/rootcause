import json

import pytest

from helpers import FLAGS, Clock
from rootcause import harness, sanitize, config
from rootcause.scenarios import Scenario
from test_snapshot import SCENARIO, fake_fetch

NAMES = sanitize.flag_names(FLAGS)


class FakeInjector:
    def __init__(self, fail_on=None, fail_restore_on=None):
        self.calls, self.fail_on, self.fail_restore_on = [], fail_on, fail_restore_on

    def apply(self, injection):
        self.calls.append("apply")
        if self.fail_on and self.fail_on in json.dumps(injection):
            raise RuntimeError("inject failed")

    def restore(self):
        self.calls.append("restore")
        if self.fail_restore_on and self.fail_restore_on in json.dumps(self.calls):
            raise RuntimeError("restore failed")


def run(tmp_path, clock, injector, scenario=SCENARIO, fetch=None):
    return harness.record(scenario, NAMES, injector, fetch=fetch or fake_fetch(t_inject=clock.t), now=clock.now,
                          sleep=clock.sleep, state_file=tmp_path / "state.json", out_dir=tmp_path / "snaps")


def failing_prom_range(*args):
    raise RuntimeError("prometheus down")


def test_record_injects_waits_captures_and_restores(tmp_path):
    clock, inj = Clock(), FakeInjector()
    # Set up state to skip cooldown (mark as restored in the past, beyond cooldown window)
    harness.mark_restored(clock.t - config.COOLDOWN_S - 1, tmp_path / "state.json")
    clock.sleeps.clear()  # Reset sleep tracking
    out = run(tmp_path, clock, inj)
    assert inj.calls == ["apply", "restore"]
    # settle_s + INGEST_LAG_S (no cooldown since we primed the state far enough in past)
    assert clock.sleeps == [SCENARIO.settle_s, config.INGEST_LAG_S]
    assert out["valid"] is True
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["last_restore"] == clock.t


def test_restore_happens_even_when_capture_fails(tmp_path):
    clock, inj = Clock(), FakeInjector()
    broken = fake_fetch()
    broken.prom_range = failing_prom_range
    with pytest.raises(RuntimeError, match="prometheus down"):
        run(tmp_path, clock, inj, fetch=broken)
    assert inj.calls == ["apply", "restore"]
    assert (tmp_path / "state.json").exists()


def test_restore_failure_writes_dirty_state_and_raises_restore_error(tmp_path):
    clock, inj = Clock(100_000.0), FakeInjector(fail_restore_on="restore")
    with pytest.raises(harness.RestoreError, match="restore failed"):
        run(tmp_path, clock, inj)
    # State should be dirty, not marked clean
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state.get("dirty") is True
    assert "error" in state


def test_restore_failure_with_prior_apply_error(tmp_path):
    """Restore failure message includes both restore error and prior in-flight error."""
    clock, inj = Clock(), FakeInjector(fail_on="adFailure", fail_restore_on="restore")
    scenario = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                        truth=SCENARIO.truth, checks=SCENARIO.checks)
    with pytest.raises(harness.RestoreError) as exc_info:
        run(tmp_path, clock, inj, scenario=scenario)
    assert "restore failed" in str(exc_info.value)
    assert "inject failed" in str(exc_info.value)


def test_restore_failure_summary_has_path_if_capture_succeeded(tmp_path):
    """When capture succeeds but restore fails, RestoreError carries the summary path."""
    clock, inj = Clock(), FakeInjector(fail_restore_on="restore")
    with pytest.raises(harness.RestoreError) as exc_info:
        run(tmp_path, clock, inj)
    # The summary should be available on the exception
    assert exc_info.value.summary is not None
    assert "path" in exc_info.value.summary


def test_cooldown_waits_for_the_remaining_time(tmp_path):
    clock = Clock()
    harness.mark_restored(clock.t - 60, tmp_path / "state.json")
    waited = harness.wait_cooldown(clock.now, clock.sleep, tmp_path / "state.json")
    assert waited == config.COOLDOWN_S - 60 and clock.sleeps == [config.COOLDOWN_S - 60]


def test_cooldown_missing_file_waits_full_cooldown(tmp_path):
    """Unknown history (missing file) means wait the full COOLDOWN_S."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    waited = harness.wait_cooldown(clock.now, clock.sleep, state_file)
    assert waited == config.COOLDOWN_S
    assert clock.sleeps == [config.COOLDOWN_S]


def test_cooldown_corrupt_file_waits_full_cooldown(tmp_path):
    """Unknown history (corrupt JSON) means wait the full COOLDOWN_S."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    state_file.write_text("not valid json")
    waited = harness.wait_cooldown(clock.now, clock.sleep, state_file)
    assert waited == config.COOLDOWN_S
    assert clock.sleeps == [config.COOLDOWN_S]


def test_cooldown_dirty_state_raises(tmp_path):
    """If state is dirty (prior restore failed), raise RuntimeError telling user to reset."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"dirty": True, "error": "prior restore failed"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="State is dirty"):
        harness.wait_cooldown(clock.now, clock.sleep, state_file)


def test_record_all_continues_after_non_restore_failure_and_writes_index(tmp_path):
    """Non-restore failures write an error row and continue (unless 3 consecutive)."""
    clock = Clock()
    bad = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                   truth=SCENARIO.truth, checks=SCENARIO.checks)
    summaries = harness.record_all([bad, SCENARIO], NAMES, FakeInjector(fail_on="adFailure"), fetch=fake_fetch(t_inject=clock.t),
                                   now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                                   out_dir=tmp_path / "snaps")
    assert [s["scenario"] for s in summaries] == ["bad", "payment-test"]
    assert "inject failed" in summaries[0]["error"]
    assert summaries[0]["valid"] is False
    assert "path" not in summaries[0]  # Error rows have no path
    assert summaries[1]["valid"] is True
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 2
    # Parse lines to verify format
    row0 = json.loads(lines[0])
    assert row0["scenario"] == "bad" and "error" in row0 and "path" not in row0 and "results" not in row0
    row1 = json.loads(lines[1])
    assert row1["scenario"] == "payment-test" and "path" in row1 and "error" not in row1 and "results" not in row1


def test_record_all_aborts_after_3_consecutive_failures(tmp_path):
    """record_all aborts (raises) after 3 consecutive non-restore failures."""
    clock = Clock()
    inj = FakeInjector(fail_on="fail")
    scenarios = [
        Scenario(id=f"bad{i}", category="easy", alert="x", inject={"flags": {"fail": "on"}},
                 truth=SCENARIO.truth, checks=SCENARIO.checks)
        for i in range(4)
    ] + [SCENARIO]
    with pytest.raises(RuntimeError, match="Aborting after 3 consecutive"):
        harness.record_all(scenarios, NAMES, inj, fetch=fake_fetch(t_inject=clock.t),
                          now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                          out_dir=tmp_path / "snaps")
    # 3 scenarios should have rows (the 3 failures before abort); 4th is not attempted
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 3
    # Last row should be the 3rd failure
    assert json.loads(lines[2])["scenario"] == "bad2"


def test_record_all_restore_error_stops_batch(tmp_path):
    """When restore fails, write the row and re-raise to stop the batch."""
    clock = Clock()
    bad = Scenario(id="bad", category="easy", alert="x", inject={},
                   truth=SCENARIO.truth, checks=SCENARIO.checks)
    inj = FakeInjector(fail_restore_on="restore")
    with pytest.raises(harness.RestoreError):
        harness.record_all([bad, SCENARIO], NAMES, inj, fetch=fake_fetch(t_inject=clock.t),
                          now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                          out_dir=tmp_path / "snaps")
    # Only first scenario should have row; second was never injected
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["scenario"] == "bad" and "error" in row and "path" in row  # capture succeeded before restore failed


def test_index_jsonl_survives_prior_lines(tmp_path):
    """Pre-existing lines in index.jsonl are preserved when appending."""
    index_file = tmp_path / "snaps" / "index.jsonl"
    index_file.parent.mkdir(parents=True, exist_ok=True)
    # Write a pre-existing line
    index_file.write_text('{"scenario": "old", "valid": true}\n', encoding="utf-8")
    # Now run record_all
    clock = Clock()
    harness.record_all([SCENARIO], NAMES, FakeInjector(), fetch=fake_fetch(t_inject=clock.t),
                      now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                      out_dir=tmp_path / "snaps")
    lines = index_file.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["scenario"] == "old"
    assert json.loads(lines[1])["scenario"] == "payment-test"

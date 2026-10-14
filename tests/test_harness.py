import json

import pytest

from helpers import FLAGS, SCENARIO, Clock, fake_fetch
from rootcause import harness, sanitize, config, snapshot
from rootcause.scenarios import Scenario

NAMES = sanitize.flag_names(FLAGS)


class FakeInjector:
    def __init__(self, fail_apply=False, fail_restore=False):
        self.calls, self.fail_apply, self.fail_restore = [], fail_apply, fail_restore

    def apply(self, injection):
        self.calls.append("apply")
        if self.fail_apply:
            raise RuntimeError("inject failed")

    def restore(self):
        self.calls.append("restore")
        if self.fail_restore:
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


class SlowInjector(FakeInjector):
    """apply() takes `delay` seconds of fake time, like a slow docker/flag write."""
    def __init__(self, clock, delay, **kw):
        super().__init__(**kw)
        self.clock, self.delay = clock, delay

    def apply(self, injection):
        super().apply(injection)
        self.clock.t += self.delay


def test_t_inject_taken_after_apply_and_t_end_is_computed(tmp_path):
    """meta timing must not encode how long apply took: t_end == t_inject + settle_s exactly, t_inject after apply."""
    clock = Clock()
    harness.mark_restored(clock.t - config.COOLDOWN_S - 1, tmp_path / "state.json")
    start, seen = clock.t, {}

    def recording_capture(scenario, t_inject, t_end, names, fetch, out_dir, demo_commit=""):
        seen.update(t_inject=t_inject, t_end=t_end, now=clock.t)
        return {"scenario": scenario.id, "path": str(out_dir / "incident__123"), "valid": True,
                "results": [], "leaks": {}}

    original_capture = snapshot.capture
    snapshot.capture = recording_capture
    try:
        harness.record(SCENARIO, NAMES, SlowInjector(clock, 7.3), fetch=fake_fetch(t_inject=clock.t), now=clock.now,
                       sleep=clock.sleep, state_file=tmp_path / "state.json", out_dir=tmp_path / "snaps")
    finally:
        snapshot.capture = original_capture
    assert seen["t_inject"] == start + 7.3                         # after apply returned
    assert seen["t_end"] == seen["t_inject"] + SCENARIO.settle_s   # computed, exactly
    assert seen["now"] == seen["t_end"] + config.INGEST_LAG_S      # still sleeps settle + ingest lag before capture


def test_in_flight_marker_written_before_apply_and_cleared_by_restore(tmp_path):
    clock, state_file, seen = Clock(), tmp_path / "state.json", {}
    harness.mark_restored(clock.t - config.COOLDOWN_S - 1, state_file)

    class Peek(FakeInjector):
        def apply(self, injection):
            seen["state"] = json.loads(state_file.read_text(encoding="utf-8"))
            super().apply(injection)

    run(tmp_path, clock, Peek())
    assert seen["state"]["dirty"] is True and seen["state"]["error"] == f"in flight: {SCENARIO.id}"
    assert seen["state"]["t"] == clock.t - SCENARIO.settle_s - config.INGEST_LAG_S
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_restore": clock.t}


def test_in_flight_marker_survives_when_the_run_is_killed(tmp_path):
    """A hard kill skips restore/mark_restored: the leftover marker blocks the next run until reset-flags."""
    clock, state_file = Clock(), tmp_path / "state.json"
    harness.mark_restored(clock.t - config.COOLDOWN_S - 1, state_file)

    class Killed(BaseException):
        pass

    class Dies(FakeInjector):
        def restore(self):
            raise Killed

    with pytest.raises(Killed):
        run(tmp_path, clock, Dies())
    assert json.loads(state_file.read_text(encoding="utf-8"))["dirty"] is True
    with pytest.raises(harness.DirtyStateError, match="in flight"):
        harness.wait_cooldown(clock.now, clock.sleep, state_file)


def test_restore_failure_writes_dirty_state_and_raises_restore_error(tmp_path):
    clock, inj = Clock(100_000.0), FakeInjector(fail_restore=True)
    with pytest.raises(harness.RestoreError, match="restore failed"):
        run(tmp_path, clock, inj)
    # State should be dirty, not marked clean
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state.get("dirty") is True
    assert "error" in state


def test_restore_failure_with_prior_apply_error(tmp_path):
    """Restore failure message includes both restore error and prior in-flight error."""
    clock, inj = Clock(), FakeInjector(fail_apply=True, fail_restore=True)
    scenario = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                        truth=SCENARIO.truth, checks=SCENARIO.checks)
    with pytest.raises(harness.RestoreError) as exc_info:
        run(tmp_path, clock, inj, scenario=scenario)
    assert "restore failed" in str(exc_info.value)
    assert "inject failed" in str(exc_info.value)


def test_restore_failure_summary_has_path_if_capture_succeeded(tmp_path):
    """When capture succeeds but restore fails, RestoreError carries the summary path."""
    clock, inj = Clock(), FakeInjector(fail_restore=True)
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
    """If state is dirty (prior restore failed), raise DirtyStateError."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"dirty": True, "error": "prior restore failed"}), encoding="utf-8")
    with pytest.raises(harness.DirtyStateError, match="State is dirty"):
        harness.wait_cooldown(clock.now, clock.sleep, state_file)


def test_cooldown_dirty_false_is_not_dirty(tmp_path):
    """If state has {"dirty": false}, it is safe (not dirty)."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"dirty": False, "last_restore": clock.t - config.COOLDOWN_S - 1}), encoding="utf-8")
    waited = harness.wait_cooldown(clock.now, clock.sleep, state_file)
    assert waited == 0.0
    assert clock.sleeps == []


def test_cooldown_empty_list_json_waits_full_cooldown(tmp_path):
    """If state file contains [], treat as unknown history."""
    clock = Clock()
    state_file = tmp_path / "state.json"
    state_file.write_text("[]")
    waited = harness.wait_cooldown(clock.now, clock.sleep, state_file)
    assert waited == config.COOLDOWN_S
    assert clock.sleeps == [config.COOLDOWN_S]


def test_record_all_continues_after_non_restore_failure_and_writes_index(tmp_path):
    """Non-restore failures write an error row and continue (unless 3 consecutive)."""
    clock = Clock()
    bad = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                   truth=SCENARIO.truth, checks=SCENARIO.checks)
    # Use an injector that fails only on injection with "adFailure" key
    class SelectiveFailInjector(FakeInjector):
        def apply(self, injection):
            self.calls.append("apply")
            if "adFailure" in json.dumps(injection):
                raise RuntimeError("inject failed")
    summaries = harness.record_all([bad, SCENARIO], NAMES, SelectiveFailInjector(), fetch=fake_fetch(t_inject=clock.t),
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
    inj = FakeInjector(fail_apply=True)
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
    inj = FakeInjector(fail_restore=True)
    with pytest.raises(harness.RestoreError):
        harness.record_all([bad, SCENARIO], NAMES, inj, fetch=fake_fetch(t_inject=clock.t),
                          now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                          out_dir=tmp_path / "snaps")
    # Only first scenario should have row; second was never injected
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["scenario"] == "bad" and "error" in row and "path" in row  # capture succeeded before restore failed


def test_record_all_dirty_state_stops_batch_without_row(tmp_path):
    """Dirty state in wait_cooldown stops batch immediately without writing a scenario row."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"dirty": True, "error": "prior restore failed"}), encoding="utf-8")
    clock = Clock()
    with pytest.raises(harness.DirtyStateError):
        harness.record_all([SCENARIO], NAMES, FakeInjector(), fetch=fake_fetch(t_inject=clock.t),
                          now=clock.now, sleep=clock.sleep, state_file=state_file,
                          out_dir=tmp_path / "snaps")
    # No scenario row written (index.jsonl doesn't exist)
    assert not (tmp_path / "snaps" / "index.jsonl").exists()


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

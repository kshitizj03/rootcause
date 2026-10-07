import json
import shutil
import subprocess

import pytest

from helpers import FLAGS, flat_span
from rootcause import cli, config, env, harness, inject, sanitize, scenarios, snapshot

INFO = ["docker", "info", "--format", "{{.NCPU}}"]


def sc(id, docker=None):
    return scenarios.Scenario(id=id, category="easy", alert="a", inject={"docker": docker} if docker else {},
                              truth={}, checks=[])


FIXED = [sc("s1", [{"action": "pause", "container": "valkey-cart"}]),
         sc("s2", [{"action": "cpus", "container": "currency", "value": 0.05}]),
         sc("s3", [{"action": "cpus", "container": "currency", "value": 0.1},
                   {"action": "pause", "container": "kafka"}]),
         sc("s4")]


@pytest.fixture
def state(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_FILE", f)
    return f


@pytest.fixture
def stack(tmp_path, monkeypatch, state):
    """Fixed scenarios, a tmp flag file, and a dirty state file."""
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    flags_file = tmp_path / "demo.flagd.json"
    shutil.copy(FLAGS, flags_file)
    state.write_text(json.dumps({"dirty": True, "error": "boom"}))
    return flags_file


def fake_run(calls, fail=None, ncpu="16\n"):
    def run(cmd):
        calls.append(cmd)
        if cmd == INFO:
            return ncpu
        if fail:
            fail(cmd)
        return ""
    return run


def reset(flags_file, run):
    cli.reset_stack(injector=inject.Injector(flags_file=flags_file, run=run), run=run)


def not_paused(cmd):
    if cmd[1] == "unpause":
        raise subprocess.CalledProcessError(1, cmd, stderr="Error response from daemon: Container x IS NOT PAUSED")


def test_parser_accepts_all_commands():
    p = cli.build_parser()
    assert p.parse_args(["record", "payment-failure-50", "control-1"]).ids == ["payment-failure-50", "control-1"]
    assert p.parse_args(["record", "--all"]).all is True
    assert p.parse_args(["leak-check"]).paths == []
    for cmd in ("up", "down", "status", "list", "reset-flags"):
        assert p.parse_args([cmd]).cmd == cmd


def test_list_prints_scenarios(capsys):
    assert cli.main(["list"]) == 0
    assert "payment-failure-50" in capsys.readouterr().out


# --- up ---

def test_up_marks_state_so_first_record_waits_full_cooldown(state, monkeypatch):
    calls = []
    monkeypatch.setattr(env, "compose", lambda *a: calls.append(a))
    assert cli.main(["up"]) == 0
    assert calls == [("up", "-d", "--quiet-pull")]
    assert "last_restore" in json.loads(state.read_text())


def test_up_does_not_clear_dirty_state(state, monkeypatch, capsys):
    state.write_text(json.dumps({"dirty": True, "error": "boom"}))
    monkeypatch.setattr(env, "compose", lambda *a: None)
    assert cli.main(["up"]) == 3
    assert json.loads(state.read_text())["dirty"] is True
    assert "reset-flags" in capsys.readouterr().err


# --- reset-flags ---

def test_reset_undoes_flags_and_docker_and_clears_dirty_state(stack, state):
    original = stack.read_text()
    # crash leftovers: a flipped flag with its backup
    shutil.copy(stack, stack.with_name(stack.name + ".orig"))
    stack.write_text(original.replace('"defaultVariant": "off"', '"defaultVariant": "on"', 1))
    calls = []
    reset(stack, fake_run(calls, not_paused))  # "not paused" must be ignored
    assert stack.read_text() == original
    assert calls == [INFO,
                     ["docker", "update", "--cpus", "16", "currency"],
                     ["docker", "unpause", "kafka"],
                     ["docker", "unpause", "valkey-cart"]]
    st = json.loads(state.read_text())
    assert "last_restore" in st and not st.get("dirty")


def test_reset_without_cpus_scenarios_does_not_query_ncpu(stack, monkeypatch):
    monkeypatch.setattr(scenarios, "load_all", lambda: [FIXED[0]])
    calls = []
    reset(stack, fake_run(calls))
    assert calls == [["docker", "unpause", "valkey-cart"]]


def test_reset_other_unpause_failure_is_collected_and_state_stays_dirty(stack, state):
    calls = []

    def fail(cmd):
        if cmd[1] == "unpause" and cmd[2] == "kafka":
            raise subprocess.CalledProcessError(1, cmd, stderr="Error: No such container: kafka")

    with pytest.raises(RuntimeError, match="kafka"):
        reset(stack, fake_run(calls, fail))
    assert ["docker", "unpause", "valkey-cart"] in calls  # later undos still ran
    assert json.loads(state.read_text())["dirty"] is True


def test_reset_oserror_does_not_abort_remaining_undos(stack, state):
    calls = []

    def fail(cmd):
        if cmd[1] == "update":
            raise OSError("docker not found")

    with pytest.raises(RuntimeError):
        reset(stack, fake_run(calls, fail))
    assert ["docker", "unpause", "valkey-cart"] in calls
    assert json.loads(state.read_text())["dirty"] is True


@pytest.mark.parametrize("bad", ["", "abc\n", "0\n"])
def test_reset_invalid_ncpu_is_an_error_and_state_stays_dirty(stack, state, bad):
    calls = []
    with pytest.raises(RuntimeError, match="NCPU"):
        reset(stack, fake_run(calls, ncpu=bad))
    assert not any(c[1] == "update" for c in calls)
    assert json.loads(state.read_text())["dirty"] is True


# --- error reporting ---

@pytest.mark.parametrize("exc", [harness.DirtyStateError("dirty"), harness.RestoreError("restore failed"),
                                 RuntimeError("reset incomplete")])
def test_main_reports_stack_errors_in_one_line_with_hint(monkeypatch, capsys, exc):
    def boom():
        raise exc
    monkeypatch.setattr(cli, "reset_stack", boom)
    assert cli.main(["reset-flags"]) == 3
    err = capsys.readouterr().err.strip()
    assert str(exc) in err and "python -m rootcause reset-flags" in err and len(err.splitlines()) == 1


def test_dirty_hint_names_the_real_command(state):
    state.write_text(json.dumps({"dirty": True, "error": "x"}))
    with pytest.raises(harness.DirtyStateError, match="python -m rootcause reset-flags"):
        harness.wait_cooldown(state_file=state)


# --- record ---

@pytest.fixture
def rec(monkeypatch):
    calls = []
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    monkeypatch.setattr(inject, "flag_variants", lambda: {})
    monkeypatch.setattr(sanitize, "flag_names", lambda: ["f"])
    monkeypatch.setattr(env, "demo_commit", lambda: "abc")
    monkeypatch.setattr(inject, "flag_targeting_errors", lambda: {})
    monkeypatch.setattr(scenarios, "validate", lambda s, v, t: [])
    monkeypatch.setattr(harness, "record_all", lambda chosen, names, injector, **kw: calls.append(chosen) or
                        [{"valid": True} for _ in chosen])
    return calls


def test_record_unknown_or_missing_ids_exit_2(rec, capsys):
    assert cli.main(["record", "nope"]) == 2
    assert cli.main(["record"]) == 2
    assert rec == []


def test_record_validation_failure_exit_2_and_nothing_recorded(rec, monkeypatch, capsys):
    monkeypatch.setattr(scenarios, "validate", lambda s, v, t: ["bad"] if s.id == "s2" else [])
    assert cli.main(["record", "--all"]) == 2
    assert rec == []
    assert "s2" in capsys.readouterr().out


def test_record_all_valid_exit_0_and_selects_ids(rec):
    assert cli.main(["record", "s1", "s3"]) == 0
    assert [s.id for s in rec[0]] == ["s1", "s3"]


def test_record_any_invalid_exit_1(rec, monkeypatch):
    monkeypatch.setattr(harness, "record_all", lambda chosen, *a, **kw: [{"valid": True}, {"valid": False}])
    assert cli.main(["record", "--all"]) == 1


# --- leak-check ---

@pytest.fixture
def snaps(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SNAPSHOTS", tmp_path)
    monkeypatch.setattr(sanitize, "flag_names", lambda: ["f"])
    return tmp_path


def test_leak_check_no_snapshots_is_a_failure(snaps, capsys):
    (snaps / "payment-failure-50__x").mkdir()  # old-style dir is not an incident snapshot
    assert cli.main(["leak-check"]) == 1
    assert "no snapshots found" in capsys.readouterr().out


def test_leak_check_clean_leaky_and_partial(snaps, monkeypatch, capsys):
    for n in ("a", "b", "c"):
        (snaps / f"incident__{n}").mkdir()

    def scan(p, names):
        if p.name == "incident__b":
            return {"x.json": ["hit"]}
        if p.name == "incident__c":
            raise FileNotFoundError("Required snapshot file missing: x")
        return {}
    monkeypatch.setattr(sanitize, "scan_snapshot", scan)
    assert cli.main(["leak-check"]) == 1
    out = capsys.readouterr().out
    assert "scanned 3 snapshots" in out and "incident__b" in out and "incident__c" in out and "missing" in out


def test_leak_check_all_clean_exit_0(snaps, monkeypatch, capsys):
    (snaps / "incident__a").mkdir()
    monkeypatch.setattr(sanitize, "scan_snapshot", lambda p, n: {})
    assert cli.main(["leak-check"]) == 0
    assert "leaks: none" in capsys.readouterr().out


# --- revalidate ---

def _index(snaps, *rows):
    (snaps / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def reval(snaps, monkeypatch):
    calls = []
    verdict = {}
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)

    def fake_validate(path, scenario, names):
        calls.append((str(path), scenario.id, names))
        return {"valid": verdict.get(scenario.id, True), "results": [{"passed": True}], "leaks": {}}
    monkeypatch.setattr(snapshot, "validate_snapshot", fake_validate)
    return calls, verdict


def _rows(snaps):
    return [json.loads(l) for l in (snaps / "index.jsonl").read_text(encoding="utf-8").splitlines()]


def test_revalidate_latest_row_per_scenario_skips_pathless_and_appends(reval, snaps, capsys):
    calls, _ = reval
    old = [{"scenario": "s1", "path": "p/old", "valid": False},
           {"scenario": "s1", "path": "p/new", "valid": False},
           {"scenario": "s2", "path": "p/s2", "valid": True},
           {"scenario": "s2", "valid": False, "error": "boom"},   # latest s2 row has no path: ignored
           {"scenario": "gone", "path": "p/gone", "valid": True}]  # no longer a scenario: ignored
    _index(snaps, *old)
    assert cli.main(["revalidate"]) == 0
    assert [(c[0], c[1]) for c in calls] == [("p/new", "s1"), ("p/s2", "s2")]
    assert calls[0][2] == ["f"]
    assert _rows(snaps)[:len(old)] == old  # earlier rows untouched
    assert _rows(snaps)[len(old):] == [
        {"scenario": "s1", "path": "p/new", "valid": True, "leaks": {}, "revalidated": True},
        {"scenario": "s2", "path": "p/s2", "valid": True, "leaks": {}, "revalidated": True}]
    assert capsys.readouterr().out.splitlines() == ["s1: valid=True (was False)", "s2: valid=True (was True)"]


def test_revalidate_filters_by_ids_and_exit_1_when_any_invalid(reval, snaps):
    calls, verdict = reval
    _index(snaps, {"scenario": "s1", "path": "p1", "valid": True}, {"scenario": "s2", "path": "p2", "valid": True})
    verdict["s2"] = False
    assert cli.main(["revalidate", "s2"]) == 1
    assert [c[1] for c in calls] == ["s2"]
    assert len(_rows(snaps)) == 3 and _rows(snaps)[-1]["valid"] is False


def test_revalidate_unknown_or_unrecorded_id_exit_2_and_nothing_written(reval, snaps):
    calls, _ = reval
    _index(snaps, {"scenario": "s1", "path": "p1", "valid": True})
    assert cli.main(["revalidate", "nope"]) == 2
    assert cli.main(["revalidate", "s1", "s3"]) == 2  # s3 is a scenario but was never recorded
    assert calls == [] and len(_rows(snaps)) == 1


def test_revalidate_without_index_exit_2(reval, snaps):
    assert cli.main(["revalidate"]) == 2


# --- resanitize ---

def _leaky_snapshot(snaps):
    path = snaps / "incident__x"
    path.mkdir()
    (path / "meta.json").write_text(json.dumps({"alert": "a", "baseline_start": 0, "fault_start": 10, "end": 20, "demo_commit": ""}))
    (path / "truth.json").write_text(json.dumps({"scenario_id": "s1"}))
    (path / "metrics.json").write_text(json.dumps({}))
    snapshot._write_jsonl_gz(path / "spans.jsonl.gz", [
        flat_span(span_id="a", service="frontend-proxy", name="router flagservice egress"), flat_span(span_id="b")])
    snapshot._write_jsonl_gz(path / "logs.jsonl.gz", [
        {"service": "frontend-proxy", "body": "POST /[redacted].v1.Service/ResolveAll via /flagservice/"},
        {"service": "payment", "body": "Payment failure: card declined"}, {"service": "cart", "body": "ok"}])
    _index(snaps, {"scenario": "s1", "path": str(path), "valid": True})
    return path


def _snap_bytes(path):
    return {n: (path / n).read_bytes() for n in ("metrics.json", "meta.json", "truth.json")}


def test_resanitize_filters_files_leaves_others_alone_is_idempotent_and_appends_row(snaps, monkeypatch, capsys):
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    real_names = json.loads(FLAGS.read_text(encoding="utf-8"))["flags"].keys()
    monkeypatch.setattr(sanitize, "flag_names", lambda: sorted(real_names))
    path = _leaky_snapshot(snaps)
    untouched = _snap_bytes(path)

    assert cli.main(["resanitize"]) == 0
    assert capsys.readouterr().out.splitlines() == ["s1: spans 2->1, logs 3->2, valid=True"]
    snap = snapshot.load(path)
    assert [s["span_id"] for s in snap["spans"]] == ["b"]
    assert [l["service"] for l in snap["logs"]] == ["payment", "cart"]
    assert _snap_bytes(path) == untouched
    assert _rows(snaps)[1:] == [{"scenario": "s1", "path": str(path), "valid": True, "leaks": {}, "revalidated": True}]

    before = snapshot.load(path)
    assert cli.main(["resanitize", "s1"]) == 0
    assert capsys.readouterr().out.splitlines() == ["s1: spans 1->1, logs 2->2, valid=True"]
    assert snapshot.load(path) == before  # gz bytes differ (mtime header); content must not
    assert _snap_bytes(path) == untouched and len(_rows(snaps)) == 3


def test_resanitize_unknown_id_exit_2_and_nothing_touched(snaps, monkeypatch):
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    path = _leaky_snapshot(snaps)
    before = (path / "spans.jsonl.gz").read_bytes()
    assert cli.main(["resanitize", "nope"]) == 2
    assert (path / "spans.jsonl.gz").read_bytes() == before and len(_rows(snaps)) == 1

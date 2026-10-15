import argparse
import json
import shutil
import subprocess

import pytest

from agent_fakes import RecordingAgent
from helpers import FLAGS, INFO, fake_run, flat_log, flat_span, write_snapshot
from rootcause import cli, config, harness, inject, sanitize, scenarios, snapshot
from rootcause import stack as stack_mod  # `stack` is a fixture below

def scenario(id, docker=None):
    return scenarios.Scenario(id=id, category="easy", alert="a", inject={"docker": docker} if docker else {},
                              truth={}, checks=[])


FIXED = [scenario("s1", [{"action": "pause", "container": "valkey-cart"}]),
         scenario("s2", [{"action": "cpus", "container": "currency", "value": 0.05}]),
         scenario("s3", [{"action": "cpus", "container": "currency", "value": 0.1},
                   {"action": "pause", "container": "kafka"}]),
         scenario("s4")]


@pytest.fixture
def state(tmp_path, monkeypatch):
    f = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_FILE", f)
    monkeypatch.setattr(config, "FLAGS_FILE", tmp_path / "demo.flagd.json")
    return f


@pytest.fixture
def stack(tmp_path, monkeypatch, state):
    """Fixed scenarios, a tmp flag file, and a dirty state file."""
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    flags_file = tmp_path / "demo.flagd.json"
    shutil.copy(FLAGS, flags_file)
    state.write_text(json.dumps({"dirty": True, "error": "boom"}))
    return flags_file


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
    required = {"eval": ["heuristic"], "summary": ["heuristic"], "mcp": ["snapshots/incident__x"],
                "eval-custom": ["examples.my_agent:solve", "--name", "my-agent"]}
    commands = ("up", "down", "status", "list", "reset-flags", "record", "leak-check", "revalidate", "resanitize",
                "eval", "eval-custom", "summary", "report", "site", "mcp")
    for cmd in commands:
        assert p.parse_args([cmd, *required.get(cmd, [])]).cmd == cmd
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == set(commands)  # no command is left out of this test


def test_list_prints_scenarios(capsys):
    assert cli.main(["list"]) == 0
    assert "payment-failure-50" in capsys.readouterr().out


# --- up ---

def test_up_marks_state_so_first_record_waits_full_cooldown(state, monkeypatch):
    calls = []
    monkeypatch.setattr(stack_mod, "compose", lambda *a: calls.append(a))
    assert cli.main(["up"]) == 0
    assert calls == [("up", "-d", "--quiet-pull")]
    assert "last_restore" in json.loads(state.read_text())


def test_up_does_not_clear_dirty_state(state, monkeypatch, capsys):
    state.write_text(json.dumps({"dirty": True, "error": "boom"}))
    monkeypatch.setattr(stack_mod, "compose", lambda *a: None)
    assert cli.main(["up"]) == 3
    assert json.loads(state.read_text())["dirty"] is True
    assert "reset-flags" in capsys.readouterr().err


def test_up_refuses_when_a_flags_backup_is_left_over(state, monkeypatch, capsys):
    config.FLAGS_FILE.with_name(config.FLAGS_FILE.name + ".orig").write_text("{}")
    monkeypatch.setattr(stack_mod, "compose", lambda *a: None)
    assert cli.main(["up"]) == 3
    assert not state.exists()
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


def test_reset_with_unloadable_scenarios_still_undoes_every_running_known_target(stack, state, monkeypatch):
    def broken():
        raise ValueError("bad yaml in x.yaml")
    monkeypatch.setattr(scenarios, "load_all", broken)
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd == INFO:
            return "16\n"
        if cmd == ["docker", "ps", "--format", "{{.Names}}"]:
            return "kafka\ncurrency\nnot-a-target\n"
        if cmd[1] == "unpause" and cmd[2] == "currency":
            raise subprocess.CalledProcessError(1, cmd, stderr="Container currency is not paused")
        return ""

    with pytest.raises(RuntimeError, match="bad yaml in x.yaml"):
        reset(stack, run)
    undos = [c for c in calls if c[1] in ("update", "unpause")]
    assert undos == [["docker", "update", "--cpus", "16", "currency"], ["docker", "update", "--cpus", "16", "kafka"],
                     ["docker", "unpause", "currency"], ["docker", "unpause", "kafka"]]
    assert json.loads(state.read_text())["dirty"] is True  # an error occurred, so still dirty


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
    monkeypatch.setattr(stack_mod, "demo_commit", lambda: "abc")
    monkeypatch.setattr(inject, "flag_targeting_errors", lambda: {})
    monkeypatch.setattr(scenarios, "validate", lambda s, v, t: [])
    monkeypatch.setattr(harness, "record_all", lambda chosen, names, injector, **kw: calls.append(chosen) or
                        [{"valid": True} for _ in chosen])
    return calls


def test_record_unknown_or_missing_ids_exit_2(rec, capsys):
    assert cli.main(["record", "nope"]) == 2
    assert "unknown scenario ids: ['nope']" in capsys.readouterr().out
    assert cli.main(["record"]) == 2
    assert "give scenario ids or --all" in capsys.readouterr().out
    assert rec == []


def test_cli_solver_keys_are_the_reported_solvers():
    from rootcause import evaluate
    assert set(cli.SOLVERS) == {s for s in evaluate.SOLVER_ORDER if not s.startswith(("laya-", "hunch-"))}


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

def _leaky_snapshot(snaps, name="incident__x"):
    spans = [flat_span(span_id="a", service="frontend-proxy", name="router flagservice egress"), flat_span(span_id="b")]
    logs = [flat_log("frontend-proxy", "POST /[redacted].v1.Service/ResolveAll via /flagservice/"),
            flat_log("checkout", "Warning: [redacted] '[redacted]' is activated, overloading queue now."),
            flat_log("payment", "Payment failure: card declined"), flat_log("cart", "ok")]
    return write_snapshot(snaps / name, spans=spans, logs=logs)


def _snap_bytes(path):
    return {n: (path / n).read_bytes() for n in ("metrics.json", "meta.json", "truth.json")}


@pytest.fixture
def resan(snaps, monkeypatch):
    monkeypatch.setattr(scenarios, "load_all", lambda: FIXED)
    names = sorted(json.loads(FLAGS.read_text(encoding="utf-8"))["flags"])
    monkeypatch.setattr(sanitize, "flag_names", lambda: names)
    path = _leaky_snapshot(snaps)
    _index(snaps, {"scenario": "s1", "path": str(path), "valid": True})
    return path


def test_resanitize_filters_files_leaves_others_alone_is_idempotent_and_appends_row(resan, snaps, capsys):
    path, untouched = resan, _snap_bytes(resan)

    assert cli.main(["resanitize"]) == 0
    assert capsys.readouterr().out.splitlines() == ["s1: spans 2->1, logs 4->2, metrics 0->0, valid=True"]
    snap = snapshot.load(path)
    assert [s["span_id"] for s in snap["spans"]] == ["b"]
    assert [l["service"] for l in snap["logs"]] == ["payment", "cart"]  # incl. legacy-stub log dropped
    assert _snap_bytes(path) == untouched
    assert _rows(snaps)[1:] == [{"scenario": "s1", "path": str(path), "valid": True, "leaks": {}, "resanitized": True}]

    before = snapshot.load(path)
    assert cli.main(["resanitize", "s1"]) == 0
    assert capsys.readouterr().out.splitlines() == ["s1: spans 1->1, logs 2->2, metrics 0->0, valid=True"]
    assert snapshot.load(path) == before  # gz bytes differ (mtime header); content must not
    assert _snap_bytes(path) == untouched and len(_rows(snaps)) == 3


def test_resanitize_unknown_id_exit_2_and_nothing_touched(resan, snaps):
    before = (resan / "spans.jsonl.gz").read_bytes()
    assert cli.main(["resanitize", "nope"]) == 2
    assert (resan / "spans.jsonl.gz").read_bytes() == before and len(_rows(snaps)) == 1


def test_resanitize_dry_run_reports_drops_and_writes_nothing(resan, snaps, capsys):
    files = {n: (resan / n).read_bytes() for n in ("spans.jsonl.gz", "logs.jsonl.gz", "metrics.json")}
    assert cli.main(["resanitize", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "s1: spans 2->1, logs 4->2, metrics 0->0"
    assert "  dropped spans by service: frontend-proxy=1" in out
    assert "  dropped logs by service: frontend-proxy=1, checkout=1" in out
    assert "router flagservice egress" in out and "overloading queue now" in out
    assert {n: (resan / n).read_bytes() for n in files} == files
    assert not (resan / "validation.json").exists() and len(_rows(snaps)) == 1


def test_resanitize_write_failure_leaves_originals_untouched(resan, monkeypatch):
    before = {n: (resan / n).read_bytes() for n in ("spans.jsonl.gz", "logs.jsonl.gz")}
    real, calls = snapshot._write_jsonl_gz, []

    def flaky(path, rows):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, rows)
    monkeypatch.setattr(snapshot, "_write_jsonl_gz", flaky)
    with pytest.raises(OSError):
        snapshot.resanitize(resan, ["paymentFailure"])
    assert {n: (resan / n).read_bytes() for n in before} == before
    assert sorted(p.name for p in resan.iterdir()) == sorted(["meta.json", "truth.json", "metrics.json"] + list(before))


def test_resanitize_bad_snapshot_is_reported_skipped_and_exit_nonzero(resan, snaps, capsys):
    good = _leaky_snapshot(snaps, "incident__y")
    (resan / "logs.jsonl.gz").write_bytes(b"not gzip")
    _index(snaps, {"scenario": "s1", "path": str(resan), "valid": True}, {"scenario": "s2", "path": str(good), "valid": True})
    spans_before = (resan / "spans.jsonl.gz").read_bytes()
    assert cli.main(["resanitize"]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("s1: error: ") and lines[1] == "s2: spans 2->1, logs 4->2, metrics 0->0, valid=True"
    assert (resan / "spans.jsonl.gz").read_bytes() == spans_before
    assert [r["scenario"] for r in _rows(snaps)[2:]] == ["s2"]  # no row for the failed id


def test_eval_and_summary_commands_parse():
    p = cli.build_parser()
    a = p.parse_args(["eval", "heuristic"])
    assert (a.cmd, a.solver, a.runs, a.ids) == ("eval", "heuristic", 1, [])
    a = p.parse_args(["eval", "agent-v0", "--runs", "5", "payment-failure-50"])
    assert (a.solver, a.runs, a.ids) == ("agent-v0", 5, ["payment-failure-50"])
    assert p.parse_args(["summary", "heuristic"]).solver == "heuristic"


def _stub_eval(monkeypatch, run):
    from rootcause import evaluate
    monkeypatch.setattr(evaluate, "run", run)
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: [{"category": "easy"}])
    monkeypatch.setattr(evaluate, "targets", lambda ids=None: [])
    monkeypatch.setattr(evaluate, "format_summary", lambda rows: "TABLE")


def test_eval_heuristic_runs_and_prints_summary(monkeypatch, capsys):
    calls = {}
    _stub_eval(monkeypatch, lambda name, solve, runs, ids, stop_on=(): calls.update(name=name, runs=runs, ids=ids) or {"completed": 3, "stopped": None})
    assert cli.main(["eval", "heuristic"]) == 0
    assert calls == {"name": "heuristic", "runs": 1, "ids": None}
    assert "TABLE" in capsys.readouterr().out


def test_eval_without_tracing_never_imports_the_opentelemetry_module(monkeypatch):
    import sys
    import rootcause
    monkeypatch.setitem(sys.modules, "rootcause.tracing", None)  # any import of it now raises ImportError
    monkeypatch.delattr(rootcause, "tracing", raising=False)
    _stub_eval(monkeypatch, lambda name, solve, runs, ids, stop_on=(): {"completed": 0, "stopped": None})
    assert cli.main(["eval", "heuristic"]) == 0


# --- eval exit codes and summary messages ---

def test_eval_unknown_or_unrecorded_ids_exit_2_and_run_nothing(monkeypatch, capsys):
    from rootcause import evaluate
    _stub_eval(monkeypatch, lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(evaluate, "targets", lambda ids=None: [("payment-failure-50", "easy", "p")])
    assert cli.main(["eval", "heuristic", "payment-failure-50", "payment-failur-50"]) == 2
    assert "unknown or unrecorded scenario ids: ['payment-failur-50']" in capsys.readouterr().out


def test_eval_quota_stop_exits_4_and_says_how_to_resume(monkeypatch, capsys):
    _stub_eval(monkeypatch, lambda name, solve, runs, ids, stop_on=(): {"completed": 2, "stopped": "QuotaExhausted: daily"})
    assert cli.main(["eval", "agent-v0"]) == 4
    out = capsys.readouterr().out
    assert "stopped: QuotaExhausted: daily" in out and "re-run the same command after the quota resets to resume" in out


def test_eval_gemini_api_error_exits_5_without_the_reset_hint(monkeypatch, capsys):
    import openai

    def boom(*a, **k):
        raise openai.OpenAIError("no choices")
    _stub_eval(monkeypatch, boom)
    assert cli.main(["eval", "agent-v0"]) == 5
    err = capsys.readouterr().err
    assert "model API error: no choices" in err and "reset-flags" not in err


def test_stack_runtime_errors_still_exit_3_with_the_hint(monkeypatch, capsys):
    from rootcause import evaluate

    def boom(*a, **k):
        raise RuntimeError("stack broke")
    monkeypatch.setattr(evaluate, "run", boom)
    assert cli.main(["eval", "heuristic"]) == 3
    assert "reset-flags" in capsys.readouterr().err


@pytest.mark.parametrize("solver", ["heuristic", "agent-v0"])
def test_summary_with_no_records_says_so(monkeypatch, capsys, solver):
    from rootcause import evaluate
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: [])
    monkeypatch.setattr(evaluate, "targets", lambda ids=None: [])
    assert cli.main(["summary", solver]) == 0
    assert f"no runs recorded for {solver}" in capsys.readouterr().out


# --- solver table, one model per batch, expected counts ---

def test_eval_agent_pins_the_batch_to_one_model(monkeypatch):
    from rootcause import agent
    _stub_eval(monkeypatch, lambda name, solve, runs, ids, stop_on=(): {"completed": 0, "stopped": None})
    monkeypatch.setattr(agent, "Agent", RecordingAgent)
    RecordingAgent.instances.clear()
    assert cli.main(["eval", "agent-v0"]) == 0
    # a per-day quota must stop the batch, not switch models mid-table
    assert [a.kw for a in RecordingAgent.instances] == [{"models": agent.MODELS[:1], "attempts": 5}]


def test_eval_and_summary_resolve_solvers_through_the_solvers_table(monkeypatch):
    from rootcause import evaluate
    seen = {}
    solve = lambda snap: None
    monkeypatch.setattr(cli, "SOLVERS", {"heuristic": lambda: ("renamed", solve, ("stop",))})
    monkeypatch.setattr(evaluate, "run", lambda name, s, runs, ids, stop_on=(): seen.update(run=(name, s, stop_on)) or {"completed": 0, "stopped": None})
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: seen.setdefault("summ", []).append(name) or [])
    monkeypatch.setattr(evaluate, "targets", lambda ids=None: [])
    assert cli.main(["eval", "heuristic"]) == 0 and cli.main(["summary", "heuristic"]) == 0
    assert seen["run"] == ("renamed", solve, ("stop",)) and seen["summ"] == ["renamed", "renamed"]


def test_summary_passes_the_library_scenario_counts_per_category(monkeypatch):
    from rootcause import evaluate
    got = {}
    from types import SimpleNamespace as S
    monkeypatch.setattr(cli.scenarios, "load_all", lambda: [S(id="a", category="easy"), S(id="b", category="easy"), S(id="c", category="control")])
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: got.update(expected=expected) or [])
    assert cli.main(["summary", "heuristic"]) == 0
    assert got["expected"] == {"easy": 2, "control": 1}

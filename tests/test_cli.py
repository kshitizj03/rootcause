import json
import shutil
import subprocess

import pytest

from helpers import FLAGS
from rootcause import cli, config, env, inject


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


def test_up_marks_state_so_first_record_waits_full_cooldown(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_FILE", state)
    calls = []
    monkeypatch.setattr(env, "compose", lambda *a: calls.append(a))
    assert cli.main(["up"]) == 0
    assert calls == [("up", "-d", "--quiet-pull")]
    assert "last_restore" in json.loads(state.read_text())


def test_reset_flags_undoes_flags_and_docker_and_clears_dirty_state(tmp_path, monkeypatch):
    flags_file = tmp_path / "demo.flagd.json"
    shutil.copy(FLAGS, flags_file)
    original = flags_file.read_text()
    # crash leftovers: a flipped flag with its backup, and a dirty state file
    shutil.copy(flags_file, flags_file.with_name(flags_file.name + ".orig"))
    flags_file.write_text(original.replace('"defaultVariant": "off"', '"defaultVariant": "on"', 1))
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"dirty": True, "error": "boom"}))
    monkeypatch.setattr(config, "STATE_FILE", state)
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[1] == "unpause":  # container not paused: docker errors, which must be ignored
            raise subprocess.CalledProcessError(1, cmd)

    cli.reset_stack(injector=inject.Injector(flags_file=flags_file, run=run), run=run)

    assert flags_file.read_text() == original
    assert ["docker", "unpause", "valkey-cart"] in calls
    assert ["docker", "update", "--cpus", "0", "currency"] in calls
    assert all(c[1] in ("unpause", "update") for c in calls)  # nothing is paused or throttled
    st = json.loads(state.read_text())
    assert "last_restore" in st and not st.get("dirty")


def test_reset_flags_reports_failed_cpu_undo_and_stays_dirty(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"dirty": True}))
    monkeypatch.setattr(config, "STATE_FILE", state)

    def run(cmd):
        if cmd[1] == "update":
            raise subprocess.CalledProcessError(1, cmd)

    inj = inject.Injector(flags_file=FLAGS.parent / "nonexistent.json", run=run)
    with pytest.raises(RuntimeError):
        cli.reset_stack(injector=inj, run=run)
    assert json.loads(state.read_text())["dirty"] is True

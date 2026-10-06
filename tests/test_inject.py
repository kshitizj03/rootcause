import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from helpers import FLAGS
from rootcause.inject import Injector, flag_targeting_errors, flag_variants


INFO = ["docker", "info", "--format", "{{.NCPU}}"]


def fake_run(calls, fail=None, ncpu="16\n"):
    """Runner fake: records commands, answers `docker info` with ncpu, optionally fails some commands."""
    def run(cmd):
        calls.append(cmd)
        if cmd == INFO:
            return ncpu
        if fail:
            fail(cmd)
        return ""
    return run


@pytest.fixture
def flags_file(tmp_path):
    f = tmp_path / "demo.flagd.json"
    shutil.copy(FLAGS, f)
    return f


def test_flag_variants():
    v = flag_variants(FLAGS)
    assert "50%" in v["paymentFailure"] and "on" in v["recommendationCacheFailure"]


def test_apply_sets_default_variant_and_restore_brings_back_original(flags_file):
    original = flags_file.read_text()
    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({"flags": {"paymentFailure": "50%", "adHighCpu": "on"}})
    flags = json.loads(flags_file.read_text())["flags"]
    assert flags["paymentFailure"]["defaultVariant"] == "50%" and flags["adHighCpu"]["defaultVariant"] == "on"
    inj.restore()
    assert flags_file.read_text() == original
    assert not flags_file.with_name(flags_file.name + ".orig").exists()


def test_unknown_variant_is_rejected_before_any_change(flags_file):
    original = flags_file.read_text()
    with pytest.raises(ValueError):
        Injector(flags_file=flags_file, run=lambda cmd: None).apply({"flags": {"paymentFailure": "999%"}})
    assert flags_file.read_text() == original


def test_docker_actions_are_undone_in_reverse(flags_file):
    calls = []
    inj = Injector(flags_file=flags_file, run=fake_run(calls))
    inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"},
                          {"action": "cpus", "container": "currency", "value": 0.05}]})
    inj.restore()
    # `--cpus 0` does not remove a limit; undo sets the limit to the host's CPU count
    assert calls == [INFO,
                     ["docker", "pause", "valkey-cart"],
                     ["docker", "update", "--cpus", "0.05", "currency"],
                     ["docker", "update", "--cpus", "16", "currency"],
                     ["docker", "unpause", "valkey-cart"]]


@pytest.mark.parametrize("bad", ["", "abc\n", "0\n", "-2\n"])
def test_invalid_ncpu_rejected_before_any_docker_change(flags_file, bad):
    calls = []
    inj = Injector(flags_file=flags_file, run=fake_run(calls, ncpu=bad))
    with pytest.raises(ValueError):
        inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"},
                              {"action": "cpus", "container": "currency", "value": 0.05}]})
    assert calls == [INFO]


def test_restore_runs_every_undo_even_if_one_fails(flags_file):
    calls = []

    def fail(cmd):
        if cmd[1] == "update" and cmd[3] == "16":
            raise RuntimeError("update failed")

    inj = Injector(flags_file=flags_file, run=fake_run(calls, fail))
    inj.apply({"flags": {"paymentFailure": "50%"},
               "docker": [{"action": "pause", "container": "valkey-cart"},
                          {"action": "cpus", "container": "currency", "value": 0.05}]})
    original = FLAGS.read_text()
    with pytest.raises(RuntimeError):
        inj.restore()
    assert ["docker", "unpause", "valkey-cart"] in calls
    assert flags_file.read_text() == original


def test_leftover_backup_resets_file_to_pristine_before_applying(flags_file):
    pristine = flags_file.read_text(encoding="utf-8")
    backup = flags_file.with_name(flags_file.name + ".orig")
    shutil.copy(flags_file, backup)

    # Corrupt the flags file (simulate crashed run with old fault)
    cfg = json.loads(pristine)
    cfg["flags"]["paymentFailure"]["defaultVariant"] = "50%"
    flags_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({"flags": {"adHighCpu": "on"}})

    flags = json.loads(flags_file.read_text(encoding="utf-8"))["flags"]
    # paymentFailure should be reset to pristine (off), not kept at 50%
    assert flags["paymentFailure"]["defaultVariant"] == "off"
    assert flags["adHighCpu"]["defaultVariant"] == "on"

    inj.restore()
    assert flags_file.read_text(encoding="utf-8") == pristine
    assert not backup.exists()


def test_file_restore_error_does_not_block_docker_undos():
    with tempfile.TemporaryDirectory() as tmp:
        flags_file = Path(tmp) / "demo.flagd.json"
        shutil.copy(FLAGS, flags_file)

        calls = []
        inj = Injector(flags_file=flags_file, run=calls.append)
        # Apply both flags and docker so that backup is created
        inj.apply({"flags": {"adHighCpu": "on"},
                   "docker": [{"action": "pause", "container": "valkey-cart"}]})

        # Patch shutil.copy to raise PermissionError during restore
        with patch("rootcause.inject.shutil.copy", side_effect=PermissionError("access denied")):
            with pytest.raises(RuntimeError) as exc_info:
                inj.restore()

            # Docker undo should still have been attempted
            assert ["docker", "unpause", "valkey-cart"] in calls
            # Error should mention the file restore error
            assert "file restore" in str(exc_info.value)


def test_unknown_docker_action_rejected_before_any_write():
    with tempfile.TemporaryDirectory() as tmp:
        flags_file = Path(tmp) / "demo.flagd.json"
        shutil.copy(FLAGS, flags_file)
        original = flags_file.read_text(encoding="utf-8")

        calls = []
        inj = Injector(flags_file=flags_file, run=calls.append)

        with pytest.raises(ValueError):
            inj.apply({"flags": {"adHighCpu": "on"},
                      "docker": [{"action": "unknown_action", "container": "valkey-cart"}]})

        # File should not be modified
        assert flags_file.read_text(encoding="utf-8") == original
        # No .orig should be created
        assert not flags_file.with_name(flags_file.name + ".orig").exists()
        # Runner should never have been called
        assert len(calls) == 0


def test_partial_docker_failure_during_apply_undoes_prior_action_only():
    with tempfile.TemporaryDirectory() as tmp:
        flags_file = Path(tmp) / "demo.flagd.json"
        shutil.copy(FLAGS, flags_file)
        pristine = flags_file.read_text(encoding="utf-8")

        calls = []

        def fail(cmd):
            if cmd[1] == "update" and cmd[3] == "0.05":
                raise RuntimeError("cpu update failed")

        inj = Injector(flags_file=flags_file, run=fake_run(calls, fail))

        # Second docker action should fail during apply
        with pytest.raises(RuntimeError):
            inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"},
                                  {"action": "cpus", "container": "currency", "value": 0.05}]})

        # First action was applied but second failed
        assert ["docker", "pause", "valkey-cart"] in calls

        # Now restore should undo just the first action
        inj.restore()
        assert ["docker", "unpause", "valkey-cart"] in calls
        # File should be pristine (no flags were changed)
        assert flags_file.read_text(encoding="utf-8") == pristine


def test_leftover_backup_reset_on_docker_only_apply(flags_file):
    """Docker-only apply should restore from backup if it exists."""
    pristine = flags_file.read_text(encoding="utf-8")
    backup = flags_file.with_name(flags_file.name + ".orig")
    shutil.copy(flags_file, backup)

    # Corrupt the flags file (simulate crashed run with old fault)
    cfg = json.loads(pristine)
    cfg["flags"]["paymentFailure"]["defaultVariant"] = "50%"
    flags_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Docker-only apply should reset file to pristine
    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"}]})

    flags = json.loads(flags_file.read_text(encoding="utf-8"))["flags"]
    assert flags["paymentFailure"]["defaultVariant"] == "off"


def test_leftover_backup_reset_on_empty_apply(flags_file):
    """Empty apply should restore from backup if it exists."""
    pristine = flags_file.read_text(encoding="utf-8")
    backup = flags_file.with_name(flags_file.name + ".orig")
    shutil.copy(flags_file, backup)

    # Corrupt the flags file (simulate crashed run with old fault)
    cfg = json.loads(pristine)
    cfg["flags"]["paymentFailure"]["defaultVariant"] = "50%"
    flags_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Empty apply should reset file to pristine
    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({})

    flags = json.loads(flags_file.read_text(encoding="utf-8"))["flags"]
    assert flags["paymentFailure"]["defaultVariant"] == "off"


def test_cpus_action_without_value_rejected_upfront(flags_file):
    """cpus action must have a value field; validation happens before any write."""
    original = flags_file.read_text(encoding="utf-8")
    calls = []

    inj = Injector(flags_file=flags_file, run=calls.append)

    with pytest.raises(ValueError):
        inj.apply({"docker": [{"action": "cpus", "container": "currency"}]})

    # File should not be modified
    assert flags_file.read_text(encoding="utf-8") == original
    # No .orig should be created
    assert not flags_file.with_name(flags_file.name + ".orig").exists()
    # Runner should never have been called
    assert len(calls) == 0


def test_restore_without_backup_is_a_noop(flags_file):
    original = flags_file.read_text()
    Injector(flags_file=flags_file, run=lambda cmd: None).restore()
    assert flags_file.read_text() == original
    assert not flags_file.with_name(flags_file.name + ".orig").exists()


COND = {"==": [{"var": "product_id"}, "OLJCESPC7Z"]}


def test_apply_sets_then_branch_of_targeting_and_restore_is_byte_identical(flags_file):
    original = flags_file.read_bytes()
    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({"flags": {"productCatalogFailure": "on"}})
    spec = json.loads(flags_file.read_text())["flags"]["productCatalogFailure"]
    assert spec["targeting"] == {"if": [COND, "on", "off"]} and spec["defaultVariant"] == "on"
    inj.restore()
    assert flags_file.read_bytes() == original


@pytest.mark.parametrize("targeting", [
    {"fractional": [["on", 50], ["off", 50]]},
    {"if": [COND, "on"]},
    {"if": [COND, "on", {"if": [COND, "on", "off"]}]},
    {"if": [COND, "nope", "off"]},
])
def test_unsupported_targeting_rejected_before_any_write(flags_file, targeting):
    cfg = json.loads(flags_file.read_text())
    cfg["flags"]["productCatalogFailure"]["targeting"] = targeting
    flags_file.write_text(json.dumps(cfg, indent=2))
    original = flags_file.read_bytes()
    calls = []
    with pytest.raises(ValueError, match="targeting"):
        Injector(flags_file=flags_file, run=calls.append).apply({"flags": {"productCatalogFailure": "on"}})
    assert flags_file.read_bytes() == original
    assert not flags_file.with_name(flags_file.name + ".orig").exists()
    assert calls == []


def test_flag_targeting_errors_flags_only_unsupported_shapes(flags_file):
    assert flag_targeting_errors(flags_file) == {}
    cfg = json.loads(flags_file.read_text())
    cfg["flags"]["productCatalogFailure"]["targeting"] = {"fractional": []}
    flags_file.write_text(json.dumps(cfg))
    assert list(flag_targeting_errors(flags_file)) == ["productCatalogFailure"]

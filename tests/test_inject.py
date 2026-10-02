import json
import shutil

import pytest

from helpers import FLAGS
from rootcause.inject import Injector, flag_variants


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
    inj = Injector(flags_file=flags_file, run=calls.append)
    inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"},
                          {"action": "cpus", "container": "currency", "value": 0.05}]})
    inj.restore()
    assert calls == [["docker", "pause", "valkey-cart"],
                     ["docker", "update", "--cpus", "0.05", "currency"],
                     ["docker", "update", "--cpus", "0", "currency"],
                     ["docker", "unpause", "valkey-cart"]]


def test_restore_runs_every_undo_even_if_one_fails(flags_file):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[1] == "update" and cmd[3] == "0":
            raise RuntimeError("update failed")

    inj = Injector(flags_file=flags_file, run=run)
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
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
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
    import tempfile
    from pathlib import Path

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
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        flags_file = Path(tmp) / "demo.flagd.json"
        shutil.copy(FLAGS, flags_file)
        pristine = flags_file.read_text(encoding="utf-8")

        calls = []

        def run(cmd):
            calls.append(cmd)
            if cmd[1] == "update" and cmd[3] == "0.05":
                raise RuntimeError("cpu update failed")

        inj = Injector(flags_file=flags_file, run=run)

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

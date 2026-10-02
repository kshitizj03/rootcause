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

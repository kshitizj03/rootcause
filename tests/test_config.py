import json

from helpers import FLAGS
from rootcause import config


def test_known_targets_cover_apps_and_infra_without_hidden():
    assert set(config.APP_SERVICES) <= set(config.KNOWN_TARGETS)
    assert set(config.INFRA_CONTAINERS) <= set(config.KNOWN_TARGETS)
    assert not config.HIDDEN_SERVICES & set(config.KNOWN_TARGETS)


def test_cooldown_covers_baseline():
    assert config.COOLDOWN_S > config.BASELINE_S


def test_fixture_matches_pinned_demo():
    backup = config.FLAGS_FILE.with_name(config.FLAGS_FILE.name + ".orig")
    source = backup if backup.exists() else config.FLAGS_FILE
    if not source.exists():
        import pytest
        pytest.skip("vendored demo not present (CI)")
    assert json.loads(source.read_text()) == json.loads(FLAGS.read_text())

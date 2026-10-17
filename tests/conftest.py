"""Setup every test shares: no recorded data from the checkout, and no RecordingAgent left over from another test."""
import pytest

from agent_fakes import RecordingAgent
from rootcause import config, evaluate


@pytest.fixture(autouse=True)
def _no_real_data(tmp_path, monkeypatch):
    """Point the data paths at a directory that does not exist; a test that needs data builds it under tmp_path."""
    data = tmp_path / "no-data"
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(config, "SNAPSHOTS", data / "snapshots")
    monkeypatch.setattr(config, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(evaluate, "RUNS_DIR", data / "runs")
    RecordingAgent.instances.clear()

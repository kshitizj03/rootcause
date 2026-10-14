import pytest

from helpers import write_record
from rootcause import cli, config, evaluate, scenarios


def test_heldout_is_one_scenario_per_category_and_exists():
    lib = {s.id: s.category for s in scenarios.load_all()}
    assert set(config.HELDOUT) <= set(lib)
    cats = [lib[i] for i in config.HELDOUT]
    assert sorted(cats) == sorted(set(lib.values())) and len(cats) == len(set(cats))
    for c in set(lib.values()):  # rule: the alphabetically last scenario of each category
        assert max(i for i, cat in lib.items() if cat == c) in config.HELDOUT


def test_summarise_filters_by_split(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    d = tmp_path / "s"
    write_record(d, "a", "easy", 0, 1.0)
    write_record(d, "b", "easy", 0, 0.0)
    rows = lambda split: {r["category"]: r["accuracy_mean"] for r in evaluate.summarise("s", tmp_path, split=split)}
    assert rows("all")["easy"] == 0.5 and rows(None)["easy"] == 0.5
    assert rows("tune")["easy"] == 1.0 and rows("heldout")["easy"] == 0.0


def test_summary_command_reports_empty_split(monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "summarise", lambda *a, **k: [])
    assert cli.main(["summary", "heuristic", "--split", "heldout"]) == 0
    assert "no runs recorded for heuristic (heldout)" in capsys.readouterr().out


def test_in_split(monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    assert [evaluate.in_split(i, s) for s in (None, "all") for i in "ab"] == [True] * 4
    assert [evaluate.in_split(i, "tune") for i in "ab"] == [True, False]
    assert [evaluate.in_split(i, "heldout") for i in "ab"] == [False, True]
    with pytest.raises(ValueError):
        evaluate.in_split("a", "held-out")


def test_summary_expected_counts_respect_the_split(monkeypatch):
    from types import SimpleNamespace as S
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    monkeypatch.setattr(cli.scenarios, "load_all", lambda: [S(id="a", category="easy"), S(id="b", category="easy"), S(id="c", category="control")])
    got = {}
    monkeypatch.setattr(evaluate, "summarise", lambda name, expected=None, split=None: got.update(e=expected, s=split) or [])
    for split, want in (("all", {"easy": 2, "control": 1}), ("tune", {"easy": 1, "control": 1}), ("heldout", {"easy": 1})):
        cli.main(["summary", "heuristic", "--split", split])
        assert got == {"e": want, "s": split}

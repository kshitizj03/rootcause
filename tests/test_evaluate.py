import json

import pytest

from rootcause import config, evaluate, scenarios, snapshot
from rootcause.score import Cause, Report

from helpers import FIXTURES  # noqa: F401  (keeps tests/ on sys.path as elsewhere)


def make_snapshot(root, name, causes):
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"alert": "x", "baseline_start": 0, "fault_start": 900, "end": 1200}))
    (d / "metrics.json").write_text("{}")
    snapshot._write_jsonl_gz(d / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(d / "logs.jsonl.gz", [])
    (d / "truth.json").write_text(json.dumps({"causes": causes}))
    return d


@pytest.fixture
def lib(tmp_path, monkeypatch):
    snaps = tmp_path / "snapshots"
    a = make_snapshot(snaps, "incident__a", [{"accept": ["payment"], "fault_type": "errors"}])
    c = make_snapshot(snaps, "incident__c", [])
    (snaps / "index.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"scenario": "pay", "path": str(a), "valid": True},
        {"scenario": "ctl", "path": str(c), "valid": True},
        {"scenario": "gone", "path": str(c), "valid": True},   # no longer in the library: ignored
    ]))
    monkeypatch.setattr(config, "SNAPSHOTS", snaps)
    monkeypatch.setattr(scenarios, "load_all", lambda: [
        scenarios.Scenario("pay", "easy", "a", {}, {}, []), scenarios.Scenario("ctl", "control", "a", {}, {}, [])])
    return tmp_path


def test_targets_resolve_latest_rows_for_library_scenarios(lib):
    assert [(s, c) for s, c, _ in evaluate.targets()] == [("ctl", "control"), ("pay", "easy")]


def test_run_scores_after_solving_and_never_shows_truth(lib):
    seen = []

    def solve(snap):
        seen.append(set(snap))
        return Report("incident", (Cause("payment", "errors"),), (), 0.9), {"solver": "fake"}

    out = evaluate.run("fake", solve, runs=2, out_dir=lib / "runs")
    assert out == {"completed": 4, "stopped": None}
    assert all(keys == {"meta", "metrics", "spans", "logs"} for keys in seen)
    rec = json.loads((lib / "runs" / "fake" / "pay__1.json").read_text())
    assert rec["score"]["correct"] == 1.0 and rec["run"] == 1 and rec["category"] == "easy"
    ctl = json.loads((lib / "runs" / "fake" / "ctl__0.json").read_text())
    assert ctl["score"]["false_alarm"] is True


def test_run_is_resumable_and_stops_cleanly(lib):
    class Stop(Exception):
        pass

    calls = []

    def solve(snap):
        calls.append(1)
        if len(calls) == 2:
            raise Stop("quota")
        return Report("no_incident"), {}

    first = evaluate.run("s", solve, runs=1, out_dir=lib / "runs", stop_on=(Stop,))
    assert first["completed"] == 1 and "quota" in first["stopped"]
    second = evaluate.run("s", solve, runs=1, out_dir=lib / "runs", stop_on=(Stop,))
    assert second == {"completed": 1, "stopped": None}
    assert len(list((lib / "runs" / "s").glob("*.json"))) == 2


def test_unexpected_solver_errors_propagate(lib):
    def solve(snap):
        raise KeyError("bug")

    with pytest.raises(KeyError):
        evaluate.run("s", solve, out_dir=lib / "runs")


def test_summarise_means_and_spread_over_runs(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    recs = [("p1", "easy", 0, 1.0), ("p2", "easy", 0, 0.0), ("p1", "easy", 1, 1.0), ("p2", "easy", 1, 1.0),
            ("c1", "control", 0, 1.0), ("c1", "control", 1, 0.0)]
    for sid, cat, k, correct in recs:
        score = {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None if cat == "control" else True,
                 "false_alarm": cat == "control" and correct == 0.0, "abstained": False}
        (d / f"{sid}__{k}.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": k, "score": score}))
    rows = {r["category"]: r for r in evaluate.summarise("x", out_dir=tmp_path)}
    assert rows["easy"]["accuracy_mean"] == 0.75 and rows["easy"]["accuracy_std"] == 0.25
    assert rows["easy"]["scenarios"] == 2 and rows["easy"]["runs"] == 2
    assert rows["control"]["false_alarm"] == 0.5 and rows["control"]["fault_type"] is None
    assert rows["all incidents"]["accuracy_mean"] == 0.75
    assert "| easy |" in evaluate.format_summary(list(rows.values()))


# --- cleanup: partial batches, record layout, console-safe table ---

def write_recs(d, recs):
    d.mkdir(exist_ok=True)
    for sid, cat, k in recs:
        score = {"correct": 1.0, "top3": True, "fault_type_ok": True, "false_alarm": False, "abstained": False}
        (d / f"{sid}__{k}.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": k, "score": score}))


def test_summarise_exposes_uneven_records_per_scenario(tmp_path):
    write_recs(tmp_path / "x", [("p1", "easy", 0), ("p1", "easy", 1), ("p1", "easy", 2), ("p2", "easy", 0)])
    rows = {r["category"]: r for r in evaluate.summarise("x", out_dir=tmp_path)}
    assert (rows["easy"]["records_min"], rows["easy"]["records_max"]) == (1, 3)
    assert (rows["all incidents"]["records_min"], rows["all incidents"]["records_max"]) == (1, 3)
    table = evaluate.format_summary(list(rows.values()))
    assert "| easy | 2 | 1-3 |" in table


def test_even_runs_show_a_single_number(tmp_path):
    write_recs(tmp_path / "x", [("p1", "easy", 0), ("p1", "easy", 1), ("p2", "easy", 0), ("p2", "easy", 1)])
    rows = evaluate.summarise("x", out_dir=tmp_path)
    assert (rows[0]["records_min"], rows[0]["records_max"]) == (2, 2)
    assert "| easy | 2 | 2 |" in evaluate.format_summary(rows)


def test_table_is_ascii_for_the_windows_console(tmp_path):
    write_recs(tmp_path / "x", [("p1", "easy", 0)])
    table = evaluate.format_summary(evaluate.summarise("x", out_dir=tmp_path))
    assert "+/-" in table and "±" not in table and table.isascii()


def test_solver_info_cannot_overwrite_record_fields(lib):
    evaluate.run("evil", lambda snap: (Report("no_incident"), {"scenario": "x", "category": "y", "run": 99, "seconds": -1,
                                                                 "report": "r", "score": "s", "extra": 1}), out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "evil" / "pay__0.json").read_text())
    assert (rec["scenario"], rec["category"], rec["run"]) == ("pay", "easy", 0)
    assert rec["seconds"] >= 0 and isinstance(rec["report"], dict) and isinstance(rec["score"], dict) and rec["extra"] == 1

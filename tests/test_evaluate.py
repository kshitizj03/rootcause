import json

import pytest

from rootcause import config, evaluate, scenarios, snapshot
from rootcause.score import Cause, Report, make_report

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
    monkeypatch.setattr(evaluate, "code_version", lambda: "abc1234")
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


# --- final review: scenario-balanced table, run-major order, code version ---

def write_scored(d, recs):
    """recs: (scenario, category, run, correct). Other score fields follow from correct."""
    d.mkdir(exist_ok=True)
    for sid, cat, k, correct in recs:
        score = {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None if cat == "control" else correct == 1.0,
                 "false_alarm": cat == "control" and correct == 0.0, "abstained": False}
        (d / f"{sid}__{k}.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": k, "score": score}))


def test_uneven_records_give_scenario_balanced_rates_and_no_sd(tmp_path):
    # p1 solved 5 times, p2 failed once: balanced accuracy is (1 + 0) / 2, not 5/6
    write_scored(tmp_path / "x", [("p1", "easy", k, 1.0) for k in range(5)] + [("p2", "easy", 0, 0.0)])
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["accuracy_mean"] == 0.5 and row["top3"] == 0.5 and row["fault_type"] == 0.5
    assert row["accuracy_std"] is None  # only run 0 covers both scenarios
    assert "| 0.50 +/- - |" in evaluate.format_summary([row])


def test_sd_uses_only_run_indices_covering_every_scenario(tmp_path):
    write_scored(tmp_path / "x", [("p1", "easy", 0, 1.0), ("p2", "easy", 0, 1.0), ("p1", "easy", 1, 0.0),
                                  ("p2", "easy", 1, 0.0), ("p1", "easy", 2, 1.0)])  # run 2 is incomplete
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["accuracy_std"] == 0.5


def test_expected_scenarios_shown_when_they_differ(tmp_path):
    write_scored(tmp_path / "x", [("p1", "easy", 0, 1.0), ("c1", "control", 0, 1.0)])
    rows = evaluate.summarise("x", out_dir=tmp_path, expected={"easy": 2, "control": 1})
    by = {r["category"]: r for r in rows}
    assert by["easy"]["expected"] == 2 and by["control"]["expected"] == 1 and by["all incidents"]["expected"] == 2
    table = evaluate.format_summary(rows)
    assert "| easy | 1/2 |" in table and "| control | 1 |" in table and "| all incidents | 1/2 |" in table


def test_format_dashes_for_meaningless_cells_and_footnotes_the_two_fault_metrics(tmp_path):
    write_scored(tmp_path / "x", [("p1", "easy", 0, 1.0), ("c1", "control", 0, 0.0)])
    lines = evaluate.format_summary(evaluate.summarise("x", out_dir=tmp_path)).splitlines()
    cells = {l.split("|")[1].strip(): [c.strip() for c in l.split("|")[2:-1]] for l in lines if l.startswith("| ") and "category" not in l}
    # columns: scenarios, runs, accuracy, top-3, fault type, false alarm, abstain
    assert cells["easy"][4:6] == ["1.00", "-"] and cells["all incidents"][5] == "-"
    assert cells["control"][3] == "-" and cells["control"][4] == "-" and cells["control"][5] == "1.00"
    assert "fault type (cause+type)" in lines[0]
    assert lines[-1] == "two-fault: accuracy = fraction of causes found; top-3 = both causes found"


def test_run_is_run_major_so_a_quota_stop_leaves_scenarios_even(lib):
    class Stop(Exception):
        pass

    calls = []

    def solve(snap):
        calls.append(1)
        if len(calls) == 4:
            raise Stop("quota")
        return Report("no_incident"), {}

    out = evaluate.run("s", solve, runs=3, out_dir=lib / "runs", stop_on=(Stop,))
    assert out["completed"] == 3
    assert sorted(p.name for p in (lib / "runs" / "s").glob("*.json")) == ["ctl__0.json", "ctl__1.json", "pay__0.json"]
    rows = evaluate.summarise("s", out_dir=lib / "runs")
    assert all(r["records_max"] - r["records_min"] <= 1 for r in rows)


def test_records_carry_the_code_version(lib):
    evaluate.run("v", lambda snap: (Report("no_incident"), {}), out_dir=lib / "runs")
    assert json.loads((lib / "runs" / "v" / "pay__0.json").read_text())["code"] == "abc1234"


def _fake_git(outputs):
    def run(cmd, **kw):
        out = outputs[cmd[1]]
        if isinstance(out, Exception):
            raise out
        return type("R", (), {"stdout": out})()
    return run


def test_code_version_is_short_sha_with_dirty_marker(monkeypatch):
    monkeypatch.setattr(evaluate.subprocess, "run", _fake_git({"rev-parse": "abc1234\n", "status": ""}))
    assert evaluate.code_version() == "abc1234"
    monkeypatch.setattr(evaluate.subprocess, "run", _fake_git({"rev-parse": "abc1234\n", "status": " M rootcause/agent.py\n"}))
    assert evaluate.code_version() == "abc1234-dirty"


def test_code_version_is_unknown_without_git(monkeypatch):
    monkeypatch.setattr(evaluate.subprocess, "run", _fake_git({"rev-parse": FileNotFoundError("git"), "status": ""}))
    assert evaluate.code_version() == "unknown"


def test_errors_column_is_the_scenario_balanced_share_of_error_records(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    score = {"correct": 0.0, "top3": False, "fault_type_ok": False, "false_alarm": False, "abstained": True}
    # p1: 1 of 4 records errored (0.25); p2: 1 of 1 (1.0) -> balanced 0.625, not 2/5
    for sid, k, err in [("p1", 0, "BadRequestError: x"), ("p1", 1, None), ("p1", 2, None), ("p1", 3, None), ("p2", 0, "BadRequestError: y")]:
        (d / f"{sid}__{k}.json").write_text(json.dumps({"scenario": sid, "category": "easy", "run": k, "score": score, "error": err}))
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["errors"] == 0.625
    assert evaluate.format_summary([row]).splitlines()[0].endswith("| errors |")
    assert evaluate.format_summary([row]).splitlines()[2].endswith("| 0.62 |")


def test_errors_column_is_a_dash_when_the_solver_never_sets_error(tmp_path):
    write_recs(tmp_path / "x", [("p1", "easy", 0)])
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["errors"] is None
    assert evaluate.format_summary([row]).splitlines()[2].endswith("| - |")


def test_records_store_the_evidence_check_and_summary_reports_grounded(lib):
    def solve(snap):
        return Report("incident", (Cause("payment", "errors"),), ("free text",), 0.5), {}

    evaluate.run("g", solve, out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "g" / "pay__0.json").read_text())
    assert rec["evidence_check"] == {"items": [{"kind": "text", "grounded": False, "distinctive": False,
                                               "reason": "free text is not checkable"}],
                                     "grounded": 0, "distinctive": 0, "total": 1}
    rows = {r["category"]: r for r in evaluate.summarise("g", lib / "runs")}
    assert rows["easy"]["grounded"] == 0.0 and rows["easy"]["distinctive"] == 0.0


def test_metric_evidence_survives_the_record_json_round_trip(lib):
    item = {"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "0 -> 0.3"}

    def solve(snap):
        return make_report({"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                            "evidence": [item], "confidence": 0.5}), {}

    evaluate.run("m", solve, out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "m" / "pay__0.json").read_text())
    assert rec["report"]["evidence"] == [item] and rec["evidence_check"]["total"] == 1


def test_grounded_is_none_without_evidence_and_shown_in_the_table(lib):
    evaluate.run("n", lambda snap: (Report("no_incident"), {}), out_dir=lib / "runs")
    rows = evaluate.summarise("n", lib / "runs")
    assert all(r["grounded"] is None and r["distinctive"] is None for r in rows)
    table = evaluate.format_summary(rows).splitlines()
    assert "| grounded | distinctive | errors |" in table[0] and table[2].endswith("| - | - | - |")


def rec(conf, correct, verdict="incident", p=1000, c=50, req=5):
    return {"scenario": "s", "category": "easy", "run": 0, "requests": req, "prompt_tokens": p,
            "completion_tokens": c, "report": {"verdict": verdict, "confidence": conf},
            "score": {"correct": correct}}


def test_coverage_curve_thresholds_descend_and_skip_abstentions():
    recs = [rec(0.9, 1.0), rec(0.9, 0.0), rec(0.5, 1.0), rec(0.2, 0.0, verdict="insufficient_evidence")]
    pts = evaluate.coverage_curve(recs)
    assert [p["threshold"] for p in pts] == [0.9, 0.5]
    assert pts[0] == {"threshold": 0.9, "coverage": 0.5, "accuracy": 0.5}
    assert pts[1]["coverage"] == 0.75 and abs(pts[1]["accuracy"] - 2 / 3) < 1e-9


def test_coverage_curve_edge_cases():
    assert evaluate.coverage_curve([]) == []
    assert evaluate.coverage_curve([rec(0.4, 0.0, verdict="insufficient_evidence")]) == []
    assert evaluate.coverage_curve([rec(0.95, 1.0), rec(0.95, 1.0)]) == [{"threshold": 0.95, "coverage": 1.0, "accuracy": 1.0}]


def test_usage_and_tokens_per_correct():
    u = evaluate.usage([rec(0.9, 1.0, p=1000, c=50, req=4), rec(0.9, 0.0, p=3000, c=150, req=8)])
    assert u == {"runs": 2, "requests_mean": 6.0, "requests_max": 8, "prompt_tokens_mean": 2000.0,
                 "completion_tokens_mean": 100.0, "tokens_per_correct": 4200.0}
    assert evaluate.usage([{"score": {"correct": 1.0}}]) is None  # heuristic records carry no usage


def test_load_records_respects_split(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    d = tmp_path / "x"
    d.mkdir()
    for sid in ("a", "b"):
        (d / f"{sid}__0.json").write_text(json.dumps({"scenario": sid, "category": "easy", "run": 0,
                                                       "score": {"correct": 1.0}}))
    assert [r["scenario"] for r in evaluate.load_records("x", tmp_path, split="tune")] == ["a"]

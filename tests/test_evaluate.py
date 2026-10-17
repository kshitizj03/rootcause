import json

import pytest

from helpers import write_record, write_snapshot
from rootcause import config, evaluate, scenarios
from rootcause.score import Cause, Report, make_report


@pytest.fixture
def lib(tmp_path, monkeypatch):
    snaps = tmp_path / "snapshots"
    a = write_snapshot(snaps / "incident__a", truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]})
    c = write_snapshot(snaps / "incident__c")
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
    for r in [("p1", "easy", 0, 1.0), ("p2", "easy", 0, 0.0), ("p1", "easy", 1, 1.0), ("p2", "easy", 1, 1.0),
              ("c1", "control", 0, 1.0), ("c1", "control", 1, 0.0)]:
        write_record(tmp_path / "x", *r)
    rows = {r["category"]: r for r in evaluate.summarise("x", out_dir=tmp_path)}
    assert rows["easy"]["accuracy_mean"] == 0.75
    assert rows["easy"]["accuracy_std"] == pytest.approx(0.5 ** 0.5 / 2)  # sample sd of run means 0.5 and 1.0
    assert rows["easy"]["scenarios"] == 2 and rows["easy"]["runs"] == 2
    assert rows["control"]["false_alarm"] == 0.5 and rows["control"]["fault_type"] is None
    assert rows["all incidents"]["accuracy_mean"] == 0.75
    assert "| easy |" in evaluate.format_summary(list(rows.values()))


# --- partial batches, record layout, console-safe table ---

def test_summarise_exposes_uneven_records_per_scenario(tmp_path):
    for sid, k in [("p1", 0), ("p1", 1), ("p1", 2), ("p2", 0)]:
        write_record(tmp_path / "x", sid, "easy", k, 1.0)
    rows = {r["category"]: r for r in evaluate.summarise("x", out_dir=tmp_path)}
    assert (rows["easy"]["records_min"], rows["easy"]["records_max"]) == (1, 3)
    assert (rows["all incidents"]["records_min"], rows["all incidents"]["records_max"]) == (1, 3)
    table = evaluate.format_summary(list(rows.values()))
    assert "| easy | 2 | 1-3 |" in table


def test_even_runs_show_a_single_number(tmp_path):
    for sid, k in [("p1", 0), ("p1", 1), ("p2", 0), ("p2", 1)]:
        write_record(tmp_path / "x", sid, "easy", k, 1.0)
    rows = evaluate.summarise("x", out_dir=tmp_path)
    assert (rows[0]["records_min"], rows[0]["records_max"]) == (2, 2)
    assert "| easy | 2 | 2 |" in evaluate.format_summary(rows)


def test_table_is_ascii_for_the_windows_console(tmp_path):
    write_record(tmp_path / "x", "p1", "easy", 0, 1.0)
    table = evaluate.format_summary(evaluate.summarise("x", out_dir=tmp_path))
    assert "+/-" in table and "±" not in table and table.isascii()


def test_solver_info_cannot_overwrite_record_fields(lib):
    evaluate.run("evil", lambda snap: (Report("no_incident"), {"scenario": "x", "category": "y", "run": 99, "seconds": -1,
                                                                 "report": "r", "score": "s", "extra": 1}), out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "evil" / "pay__0.json").read_text())
    assert (rec["scenario"], rec["category"], rec["run"]) == ("pay", "easy", 0)
    assert rec["seconds"] >= 0 and isinstance(rec["report"], dict) and isinstance(rec["score"], dict) and rec["extra"] == 1


# --- scenario-balanced table, run-major order, code version ---

def test_uneven_records_give_scenario_balanced_rates_and_no_sd(tmp_path):
    # p1 solved 5 times, p2 failed once: balanced accuracy is (1 + 0) / 2, not 5/6
    for r in [("p1", "easy", k, 1.0) for k in range(5)] + [("p2", "easy", 0, 0.0)]:
        write_record(tmp_path / "x", *r)
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["accuracy_mean"] == 0.5 and row["top3"] == 0.5 and row["fault_type"] == 0.5
    assert row["accuracy_std"] is None  # only run 0 covers both scenarios
    assert "| 0.50 +/- - |" in evaluate.format_summary([row])


def test_sd_uses_only_run_indices_covering_every_scenario(tmp_path):
    for r in [("p1", "easy", 0, 1.0), ("p2", "easy", 0, 1.0), ("p1", "easy", 1, 0.0),
              ("p2", "easy", 1, 0.0), ("p1", "easy", 2, 1.0)]:  # run 2 is incomplete
        write_record(tmp_path / "x", *r)
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["accuracy_std"] == pytest.approx(0.5 ** 0.5)  # sample sd (n - 1) of run means 1.0 and 0.0


def test_expected_scenarios_shown_when_they_differ(tmp_path):
    write_record(tmp_path / "x", "p1", "easy", 0, 1.0)
    write_record(tmp_path / "x", "c1", "control", 0, 1.0)
    rows = evaluate.summarise("x", out_dir=tmp_path, expected={"easy": 2, "control": 1})
    by = {r["category"]: r for r in rows}
    assert by["easy"]["expected"] == 2 and by["control"]["expected"] == 1 and by["all incidents"]["expected"] == 2
    table = evaluate.format_summary(rows)
    assert "| easy | 1/2 |" in table and "| control | 1 |" in table and "| all incidents | 1/2 |" in table


def test_format_dashes_for_meaningless_cells_and_footnotes_the_two_fault_metrics(tmp_path):
    write_record(tmp_path / "x", "p1", "easy", 0, 1.0)
    write_record(tmp_path / "x", "c1", "control", 0, 0.0)
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
    score = {"correct": 0.0, "top3": False, "fault_type_ok": False, "false_alarm": False, "abstained": True}
    # p1: 1 of 4 records errored (0.25); p2: 1 of 1 (1.0) -> balanced 0.625, not 2/5
    for sid, k, err in [("p1", 0, "BadRequestError: x"), ("p1", 1, None), ("p1", 2, None), ("p1", 3, None), ("p2", 0, "BadRequestError: y")]:
        write_record(tmp_path / "x", sid, "easy", k, 0.0, score=score, error=err)
    row = evaluate.summarise("x", out_dir=tmp_path)[0]
    assert row["errors"] == 0.625
    assert evaluate.format_summary([row]).splitlines()[0].endswith("| errors |")
    assert evaluate.format_summary([row]).splitlines()[2].endswith("| 0.62 |")


def test_errors_column_is_a_dash_when_the_solver_never_sets_error(tmp_path):
    write_record(tmp_path / "x", "p1", "easy", 0, 1.0)
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


def usage_record(conf, correct, verdict="incident", p=1000, c=50, req=5):
    return {"scenario": "s", "category": "easy", "run": 0, "requests": req, "prompt_tokens": p,
            "completion_tokens": c, "report": {"verdict": verdict, "confidence": conf},
            "score": {"correct": correct}}


def test_coverage_curve_thresholds_descend_and_skip_abstentions():
    recs = [usage_record(0.9, 1.0), usage_record(0.9, 0.0), usage_record(0.5, 1.0), usage_record(0.2, 0.0, verdict="insufficient_evidence")]
    pts = evaluate.coverage_curve(recs)
    assert [p["threshold"] for p in pts] == [0.9, 0.5]
    assert pts[0] == {"threshold": 0.9, "coverage": 0.5, "accuracy": 0.5}
    assert pts[1]["coverage"] == 0.75 and abs(pts[1]["accuracy"] - 2 / 3) < 1e-9


def test_coverage_curve_edge_cases():
    assert evaluate.coverage_curve([]) == []
    assert evaluate.coverage_curve([usage_record(0.4, 0.0, verdict="insufficient_evidence")]) == []
    assert evaluate.coverage_curve([usage_record(0.95, 1.0), usage_record(0.95, 1.0)]) == [{"threshold": 0.95, "coverage": 1.0, "accuracy": 1.0}]


def test_coverage_curve_counts_controls_and_is_selective_accuracy():
    control = {**usage_record(0.8, 1.0), "category": "control", "report": {"verdict": "no_incident", "confidence": 0.8}}
    assert evaluate.coverage_curve([control, usage_record(0.8, 0.0)]) == [{"threshold": 0.8, "coverage": 1.0, "accuracy": 0.5}]
    # an abstention lowers the table's accuracy (counted wrong) but not the curve's lowest-threshold point
    recs = [usage_record(0.9, 1.0), usage_record(0.2, 0.0, verdict="insufficient_evidence")]
    assert evaluate.coverage_curve(recs) == [{"threshold": 0.9, "coverage": 0.5, "accuracy": 1.0}]
    assert sum(r["score"]["correct"] for r in recs) / len(recs) == 0.5


def test_usage_with_no_correct_run_and_with_mixed_records():
    assert evaluate.usage([usage_record(0.9, 0.0), usage_record(0.9, 0.0)])["tokens_per_correct"] is None
    u = evaluate.usage([usage_record(0.9, 1.0, p=1000, c=50, req=4), {"score": {"correct": 1.0}}])  # a record without usage is skipped
    assert u["runs"] == 1 and u["tokens_per_correct"] == 1050.0


def test_usage_and_tokens_per_correct():
    u = evaluate.usage([usage_record(0.9, 1.0, p=1000, c=50, req=4), usage_record(0.9, 0.0, p=3000, c=150, req=8)])
    assert u == {"runs": 2, "requests_mean": 6.0, "requests_max": 8, "prompt_tokens_mean": 2000.0,
                 "completion_tokens_mean": 100.0, "tokens_per_correct": 4200.0}
    assert evaluate.usage([{"score": {"correct": 1.0}}]) is None  # heuristic records carry no usage


def test_load_records_respects_split(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    for sid in ("a", "b"):
        write_record(tmp_path / "x", sid, "easy", 0, 1.0)
    assert [r["scenario"] for r in evaluate.load_records("x", tmp_path, split="tune")] == ["a"]


def test_folders_starting_with_an_underscore_are_never_solvers(tmp_path):
    for d in ("_discarded", "mine"):
        write_record(tmp_path / d, "a", "easy", 0, 1.0)
    assert evaluate.recorded_solvers(tmp_path) == ["mine"]
    assert evaluate.listed_solvers(tmp_path) == evaluate.SOLVER_ORDER + ["mine"]


def test_targets_skip_a_newer_failed_recording_and_refuse_a_scenario_with_no_valid_one(lib):
    index = lib / "snapshots" / "index.jsonl"
    with open(index, "a", encoding="utf-8") as f:
        f.write("\n" + json.dumps({"scenario": "pay", "path": "incident__failed", "valid": False}))
    assert dict((s, p) for s, _, p in evaluate.targets())["pay"] == str(lib / "snapshots" / "incident__a")
    index.write_text("\n".join(json.dumps(r) for r in [
        {"scenario": "pay", "path": "incident__a", "valid": True, "leaks": {}},
        {"scenario": "ctl", "path": "incident__c", "valid": True, "leaks": {"logs.jsonl.gz": ["x"]}}]), encoding="utf-8")
    assert [s for s, _, _ in evaluate.targets(["pay", "not-in-library"])] == ["pay"]
    with pytest.raises(evaluate.NoValidSnapshot, match="ctl"):
        evaluate.targets()


def test_records_name_their_snapshot_and_resume_refuses_to_mix_snapshots(lib):
    solve = lambda snap: (Report("no_incident"), {})
    evaluate.run("s", solve, runs=1, out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "s" / "pay__0.json").read_text())
    assert rec["snapshot"] == "incident__a"
    index = lib / "snapshots" / "index.jsonl"  # pay re-recorded: a newer valid snapshot
    index.write_text(index.read_text() + "\n" + json.dumps({"scenario": "pay", "path": "incident__c", "valid": True}))
    with pytest.raises(evaluate.SnapshotChanged, match="pay__0.json was scored on snapshot incident__a"):
        evaluate.run("s", solve, runs=2, out_dir=lib / "runs")
    assert not (lib / "runs" / "s" / "pay__1.json").exists() and not (lib / "runs" / "s" / "ctl__1.json").exists()
    del rec["snapshot"]  # records from before the field resume as before
    (lib / "runs" / "s" / "pay__0.json").write_text(json.dumps(rec))
    assert evaluate.run("s", solve, runs=2, out_dir=lib / "runs")["completed"] == 2

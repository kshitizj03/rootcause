import json

import pytest

from helpers import series, write_record, write_snapshot
from rootcause import config, evaluate, report, scenarios


def write(runs, solver, sid, cat, k, correct, conf=0.8, tokens=True, evidence=True):
    extra = {"report": {"verdict": "incident" if cat != "control" else "no_incident", "confidence": conf}}
    if evidence:
        extra["evidence_check"] = {"grounded": 1, "distinctive": 1, "total": 1}
    if tokens:
        extra.update(requests=5, prompt_tokens=1000, completion_tokens=50)
    write_record(runs / solver, sid, cat, k, correct, **extra)


def test_build_writes_markdown_and_figures_and_marks_missing_solvers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("c",))
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("a", "easy", "x", {}, {}, []),
                                                        scenarios.Scenario("c", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    write(runs, "heuristic", "a", "easy", 0, 1.0, tokens=False)
    write(runs, "heuristic", "c", "control", 0, 1.0, tokens=False)
    for k in range(2):
        write(runs, "agent-v1", "a", "easy", k, float(k), conf=0.9 - k / 10)
        write(runs, "agent-v1", "c", "control", k, 1.0)
    path = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v1", "agent-v1-vague"])
    md = path.read_text(encoding="utf-8")
    for heading in ("Accuracy by category", "False alarms", "Evidence", "Cost", "Per-scenario", "coverage", "Not run"):
        assert heading.lower() in md.lower()
    assert "agent-v1-vague" in md.split("Not run")[1] and "20 requests" in md
    assert "| c* | control | 1.00 (1 run) | 1.00 (2 runs) | not run |" in md  # held-out scenarios are marked
    assert (tmp_path / "out" / "figures" / "accuracy_by_category.png").stat().st_size > 1000
    assert (tmp_path / "out" / "figures" / "coverage.png").stat().st_size > 1000


def test_build_with_no_records_at_all_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, "load_all", lambda: [])
    path = report.build(out_dir=tmp_path / "out", runs_dir=tmp_path / "runs", solvers=["heuristic"])
    assert "not run" in path.read_text(encoding="utf-8").lower()


def test_report_content_cells_partial_batches_and_small_n(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("c",))
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("a", "easy", "x", {}, {}, []),
                                                        scenarios.Scenario("b", "easy", "x", {}, {}, []),
                                                        scenarios.Scenario("c", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    for sid, cat, correct in (("a", "easy", 1.0), ("b", "easy", 0.0), ("c", "control", 1.0)):
        write(runs, "heuristic", sid, cat, 0, correct, tokens=False, evidence=False)
    # uneven batch: a has 2 runs, b has 1, c has 2
    for sid, cat, k, correct, conf in (("a", "easy", 0, 1.0, 0.9), ("a", "easy", 1, 0.0, 0.8), ("b", "easy", 0, 1.0, 0.8),
                                       ("c", "control", 0, 1.0, 0.8), ("c", "control", 1, 1.0, 0.8)):
        write(runs, "agent-v1", sid, cat, k, correct, conf=conf)
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v1", "agent-v1-vague"]).read_text(encoding="utf-8")
    # accuracy cells carry scenario count and runs per scenario
    assert "| easy | 0.50 ± - (2/2 sc, 1 run) | 0.75 ± - (2/2 sc, 1-2 runs) | not run |" in md
    assert "| control | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± 0.00 (1/1 sc, 2 runs) | not run |" in md  # held-out table, n per cell
    assert "held-out categories have one scenario each; read the all-incidents row" in md.lower()
    # partial-batch note against the planned runs (agent-v1: 5, heuristic: 1), not for the complete heuristic batch
    assert "agent-v1: partial batch (1-2 runs per scenario, 5/15 runs)" in md
    assert "agent-v1: partial batch (1-2 runs per scenario, 3/10 runs)" in md
    assert "agent-v1: partial batch (2 runs per scenario, 2/5 runs)" in md
    assert md.count("agent-v1: partial batch") == 6  # under the all, tune and held-out tables, the paired comparisons,
    # the run-to-run agreement and the calibration
    assert "heuristic: partial" not in md
    # per-scenario cells show mean (n runs)
    assert "| a | easy | 1.00 (1 run) | 0.50 (2 runs) | not run |" in md
    assert "| c* | control | 1.00 (1 run) | 1.00 (2 runs) | not run |" in md
    # cost: runs with usage / records
    assert "| heuristic | 0 / 3 | - | - | - | - | - |" in md
    assert "| agent-v1 | 5 / 5 | 5.00 | 5 | 1000 | 50 |" in md
    # evidence: records without evidence_check are flagged, not shown as "-"
    assert "| heuristic | n/a (predates evidence checks) | n/a (predates evidence checks) |" in md
    assert "| agent-v1 | 1.00 | 1.00 |" in md
    # coverage: nearest curve point to 50% (threshold 0.9 -> 20% coverage), with the partial-batch caveat
    line = next(l for l in md.splitlines() if l.startswith("agent-v1: accuracy"))
    assert "accuracy 1.00 at 20% coverage" in line and "partial batch (1-2 runs per scenario, 5/15 runs)" in line.lower()


def test_evidence_provenance_and_wording(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("a", "easy", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    write(runs, "heuristic", "a", "easy", 0, 1.0, tokens=False, evidence=False)
    for solver, codes, kinds in (("agent-v1", ("abc", "def-dirty"), ["metric", "text"]), ("agent-v1-vague", ("abc",), ["text", "text"])):
        for k, code in enumerate(codes):
            write(runs, solver, "a", "easy", k, 1.0)
            f = runs / solver / f"a__{k}.json"
            r = json.loads(f.read_text())
            r["code"] = code
            r["evidence_check"] = {"grounded": 0, "distinctive": 0, "total": 2, "items": [{"kind": x} for x in kinds]}
            f.write_text(json.dumps(r))
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v1", "agent-v1-vague"]).read_text(encoding="utf-8")
    assert "| agent-v1-vague | n/a (free-text evidence) | n/a (free-text evidence) |" in md  # all checked items are text
    assert "| agent-v1 | 0.00 | 0.00 |" in md  # one non-text item per record: real numbers
    assert "| heuristic | n/a (predates evidence checks) |" in md
    assert "neither proves that the incident caused it" in md and "## Accuracy vs coverage (all split, record-level)" in md
    prov = md.split("## Provenance")[1]
    assert "agent-v1: abc, def-dirty" in prov and "agent-v1-vague: abc" in prov and "heuristic: unknown" in prov
    assert report.DISCLOSURE in prov


def test_paired_counts_wins_ties_losses_and_bootstraps_a_ci_over_incidents():
    a = {"x": 1.0, "y": 1.0, "z": 0.5, "w": 0.0, "v": 1.0, "only_a": 1.0}
    b = {"x": 0.0, "y": 1.0, "z": 0.0, "w": 0.0, "v": 1.0, "only_b": 0.0}
    p = report.paired(a, b)
    assert (p["n"], p["wins"], p["ties"], p["losses"]) == (5, 2, 3, 0)  # only incidents both solvers ran are paired
    assert p["mean_diff"] == 0.3 and p["ci"] == (0.0, 0.7)  # pinned: 2.5% / 97.5% of 10,000 resampled means
    assert report.paired(a, b) == p  # fixed seed: the report is reproducible
    q = report.paired(b, a)
    assert (q["wins"], q["losses"], q["mean_diff"], q["ci"]) == (0, 2, -0.3, (-0.7, 0.0))
    # too few incidents, or no spread: no interval rather than a falsely certain one
    assert report.paired({"x": 1.0}, {"x": 0.0})["ci"] is None
    assert report.paired(dict.fromkeys("vwxyz", 1.0), dict.fromkeys("vwxyz", 0.0))["ci"] is None
    assert report.paired({}, {"x": 1.0}) is None


def test_report_has_a_paired_section_for_solver_pairs_with_records(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario(s, "easy", "x", {}, {}, []) for s in "ab"]
                        + [scenarios.Scenario("c", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    for sid, cat, h, v in (("a", "easy", 0.0, 1.0), ("b", "easy", 1.0, 1.0), ("c", "control", 1.0, 0.0)):
        write(runs, "heuristic", sid, cat, 0, h, tokens=False)
        write(runs, "agent-v1", sid, cat, 0, v)
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v0", "agent-v1"]).read_text(encoding="utf-8")
    sec = md.split("## Paired comparisons")[1].split("\n## ")[0]
    na = "n/a (too few incidents or no spread)"  # fault-only columns first, then the same pair with the control
    assert f"| agent-v1 vs heuristic | 2/2 | 1 / 1 / 0 | +0.50 | {na} | +0.00 | {na} |" in sec
    assert "agent-v0" not in sec  # no records, no row


def test_step_limit_section_counts_runs_told_the_limit_was_reached_not_turn_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario(s, "easy", "x", {}, {}, []) for s in "abcd"]
                        + [scenarios.Scenario("c0", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    told = [{"role": "user", "content": "Step limit reached. Give your final answer now as ONLY the JSON object."}]

    def put(solver, sid, turns, verdict, correct, messages=(), **flag):
        write(runs, solver, sid, "control" if sid == "c0" else "easy", 0, correct)
        f = runs / solver / f"{sid}__0.json"
        r = json.loads(f.read_text())
        r.update(turns=turns, messages=list(messages), **flag)
        r["report"]["verdict"] = verdict
        f.write_text(json.dumps(r))

    # 15-turn limit: a and d were told; b answered on its 15th turn by itself; c0 is a control (left out)
    put("agent-v1", "a", 15, "no_incident", 0.0, told)
    put("agent-v1", "b", 15, "incident", 1.0)
    put("agent-v1", "c", 4, "incident", 1.0)
    put("agent-v1", "d", 15, "no_incident", 0.0, told)
    put("agent-v1", "c0", 15, "no_incident", 1.0, told)
    # 30-turn limit: 15 turns is well inside it; only the 30-turn run was told; a newer record carries the flag
    put("agent-v1-nemotron-steps30", "a", 15, "incident", 1.0)
    put("agent-v1-nemotron-steps30", "b", 30, "no_incident", 0.0, told)
    put("agent-v1-nemotron-steps30", "c", 30, "incident", 1.0, hit_step_limit=False)
    put("agent-v1-nemotron-steps30", "d", 12, "incident", 0.0, hit_step_limit=True)
    write(runs, "heuristic", "a", "easy", 0, 1.0, tokens=False)
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs,
                      solvers=["heuristic", "agent-v1", "agent-v1-nemotron-steps30"]).read_text(encoding="utf-8")
    sec = md.split("## Step limit")[1].split("\n## ")[0]
    assert "15 model turns; 30 for the 30-step ablation" in sec
    assert "| agent-v1 | 4 | 2 (50%) | 2 of 2 | 0.00 | 1.00 |" in sec
    assert "| agent-v1-nemotron-steps30 | 4 | 2 (50%) | 1 of 2 | 0.00 | 1.00 |" in sec
    assert "heuristic" not in sec  # no model, no step limit


def test_partial_batches_are_measured_against_planned_runs(monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario(f"s{i}", "easy", "x", {}, {}, []) for i in range(20)])
    recs = [{"scenario": f"s{i}"} for i in range(20)] + [{"scenario": f"s{i}"} for i in range(12)]  # 32 runs: 1-2 each
    data = {"records": {"agent-v0": recs, "heuristic": recs[:20], "agent-v1": []}}
    assert report._partial(data, "agent-v0", "all") == "1-2 runs per scenario, 32/100 runs"
    assert report._label(data, "agent-v0") == "agent-v0 (partial, 32/100)"
    assert report._partial(data, "heuristic", "all") is None and report._label(data, "heuristic") == "heuristic"  # 1 planned
    assert report._partial(data, "agent-v1", "all") is None  # no runs: "not run", not partial


def test_build_lists_the_built_in_solvers_then_every_other_solver_with_records(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("a", "easy", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    for solver in ("heuristic", "my-agent", "agent-v1@gemma-4-26b-a4b-it", "laya-english", "hunch-0.6b", "_discarded"):
        write(runs, solver, "a", "easy", 0, 1.0)
    (runs / "empty").mkdir()  # a directory without records is not a solver
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs).read_text(encoding="utf-8")
    per_scenario = md.split("## Per-scenario accuracy")[1].split("\n\n")[2].splitlines()[0]
    # experiments stay in the tables, after the built-in agents; a folder starting with "_" is set aside, not a solver
    assert per_scenario.endswith("| agent-v1-nemotron-steps30 | agent-v1@gemma-4-26b-a4b-it | hunch-0.6b | laya-english | my-agent |")
    assert "| a | easy | 1.00 (1 run) |" in md and "| my-agent | 1.00 | 1.00 |" in md and "empty" not in md
    assert "_discarded" not in md


def _top_rec(sid, top, conf, correct):
    causes = [] if top in ("no_incident", "insufficient_evidence") else [{"service": top, "fault_type": "errors"}]
    return {"scenario": sid, "report": {"verdict": "incident" if causes else top, "causes": causes, "confidence": conf},
            "score": {"correct": correct}}


# a: top answers payment, payment, cart; b: no_incident twice (one confidence is not a number); c: one run
RECS = [_top_rec("a", "payment", 0.9, 1.0), _top_rec("a", "payment", 0.9, 1.0), _top_rec("a", "cart", 0.3, 0.0),
        _top_rec("b", "no_incident", 0.7, 1.0), _top_rec("b", "no_incident", "high", 1.0), _top_rec("c", "payment", 0.1, 0.0)]


def test_agreement_counts_scenarios_with_two_runs_and_averages_pairwise_agreement():
    # a: 1 agreeing pair of 3 (1/3), not unanimous; b: 1 of 1, unanimous; c: one run, left out -> (1/3 + 1) / 2
    assert report.agreement(RECS) == (2, 1, pytest.approx(2 / 3))
    assert report.agreement(RECS[:1]) is None


def test_calibration_by_hand():
    # 5 numeric confidences: (0.9,1) (0.9,1) (0.3,0) (0.7,1) (0.1,0); mean 2.9/5, accuracy 3/5.
    # ECE bins: [0.8,1] 2/5*0.1 + [0.2,0.4) 1/5*0.3 + [0.6,0.8) 1/5*0.3 + [0,0.2) 1/5*0.1 = 0.18
    # Brier: (0.01 + 0.01 + 0.09 + 0.09 + 0.01) / 5 = 0.042
    assert report.calibration(RECS) == pytest.approx({"runs": 5, "skipped": 1, "confidence": 0.58, "accuracy": 0.6,
                                                      "ece": 0.18, "brier": 0.042})
    assert report.calibration([_top_rec("a", "payment", None, 1.0)]) is None
    assert evaluate.confidence({"report": {"confidence": True}}) is None and evaluate.confidence({"report": {}}) is None
    assert report.calibration([_top_rec("a", "payment", 1.0, 1.0)])["ece"] == 0  # confidence 1 falls in the top bin


def test_agreement_and_calibration_sections_cover_agents_with_repeated_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario(s, "easy", "x", {}, {}, []) for s in "abc"])
    runs, k = tmp_path / "runs", {}
    for r in RECS:
        k[r["scenario"]] = k.get(r["scenario"], -1) + 1
        write_record(runs / "agent-v1", r["scenario"], "easy", k[r["scenario"]], r["score"]["correct"], report=r["report"])
    for i in range(2):  # agent-v0: sure and wrong twice on a
        write_record(runs / "agent-v0", "a", "easy", i, 0.0, report=_top_rec("a", "cart", 0.9, 0.0)["report"])
    for sid in "abc":  # one run each: a baseline, not in these sections
        write_record(runs / "heuristic", sid, "easy", 0, 1.0, report=_top_rec(sid, "payment", 0.5, 1.0)["report"])
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v0", "agent-v1"]).read_text(encoding="utf-8")
    assert md.index("## Step limit") < md.index("## Run-to-run agreement") < md.index("## Calibration") < md.index("## Cost")
    agree = md.split("## Run-to-run agreement (all incidents)")[1].split("\n## ")[0]
    assert "| agent-v0 | 1 | 1 of 1 | 1.00 |" in agree and "| agent-v1 | 2 | 1 of 2 | 0.67 |" in agree
    cal = md.split("## Calibration (all incidents, record-level)")[1].split("\n## ")[0]
    assert "| agent-v0 | 2 | 0.90 | 0.00 | 0.90 | 0.81 |" in cal and "| agent-v1 | 5 | 0.58 | 0.60 | 0.18 | 0.04 |" in cal
    assert "overconfident) for agent-v0, and not for agent-v1." in cal
    assert "Runs without a numeric confidence are skipped: agent-v1: 1." in cal
    assert "heuristic" not in agree + cal


def test_failure_modes_classify_each_wrong_fault_run():
    accept = {"a": {"payment"}, "b": {"valkey-cart"}, "c": {"ad"}, "d": {"x", "y"}}
    top = {"a": "checkout", "b": "cart", "c": "ad"}
    rec = lambda sid, verdict, causes, correct, cat="easy": {"scenario": sid, "category": cat, "score": {"correct": correct},
                                                             "report": {"verdict": verdict, "causes": [{"service": s} for s in causes]}}
    records = [rec("a", "no_incident", [], 0.0), rec("a", "incident", ["checkout"], 0.0),            # no incident; symptom
               rec("b", "incident", ["cart", "valkey-cart"], 0.0), rec("b", "insufficient_evidence", [], 0.0),  # ranked 2nd; abstained
               rec("c", "incident", ["email"], 0.0), rec("d", "incident", ["x"], 0.5),                 # other service; one of two
               rec("c", "incident", ["ad"], 1.0), rec("a", "no_incident", [], 1.0, "control")]       # right, control: not counted
    c = report.failure_modes(records, accept, top)
    assert c == {"said no incident": 1, "named the top-changed service": 1, "true cause ranked 2nd or 3rd": 1,
                 "abstained": 1, "another wrong service": 1, "found one of two causes": 1}
    assert report.failure_modes(records, accept, {})["another wrong service"] == 2  # without snapshots: no symptom call


def test_failure_modes_section_names_the_top_changed_service_from_the_recorded_snapshot(tmp_path, monkeypatch):
    snaps = tmp_path / "snapshots"
    write_snapshot(snaps / "incident__a", metrics={"error_ratio": {"checkout": series(0.0, 0.5), "payment": series(0.0, 0.0)}})
    (snaps / "index.jsonl").write_text(json.dumps({"scenario": "a", "path": "incident__a", "valid": True}) + "\n")
    monkeypatch.setattr(config, "SNAPSHOTS", snaps)
    monkeypatch.setattr(scenarios, "load_all", lambda: [
        scenarios.Scenario("a", "easy", "x", {}, {"causes": [{"accept": ["payment"], "fault_type": "errors"}]}, [])])
    runs = tmp_path / "runs"
    write_record(runs / "agent-v1", "a", "easy", 0, 0.0, report={"verdict": "incident", "confidence": 0.8,
                                                              "causes": [{"service": "checkout", "fault_type": "errors"}]})
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["agent-v1"]).read_text(encoding="utf-8")
    section = md.split("## Failure modes")[1].split("\n## ")[0]
    assert "Recorded snapshots not found" not in section
    assert "| agent-v1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 |" in section  # the one wrong run named the symptom service

import json

from helpers import write_record
from rootcause import config, report, scenarios


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
    assert md.count("agent-v1: partial batch") == 4  # under the all, tune and held-out tables, and the paired comparisons
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
    assert "| agent-v1 vs heuristic | 2/2 | 1 / 1 / 0 | +0.50 | n/a (too few incidents or no spread) |" in sec  # no controls
    assert "agent-v0" not in sec  # no records, no row


def test_step_limit_section_splits_fault_runs_by_whether_they_hit_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ())
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario(s, "easy", "x", {}, {}, []) for s in "abcd"]
                        + [scenarios.Scenario("c0", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    for sid, turns, verdict, correct in (("a", 15, "no_incident", 0.0), ("b", 15, "incident", 1.0), ("c", 4, "incident", 1.0),
                                         ("d", 15, "no_incident", 0.0), ("c0", 15, "no_incident", 1.0)):
        write(runs, "agent-v1", sid, "control" if sid == "c0" else "easy", 0, correct)
        f = runs / "agent-v1" / f"{sid}__0.json"
        r = json.loads(f.read_text())
        r["turns"], r["report"]["verdict"] = turns, verdict
        f.write_text(json.dumps(r))
    write(runs, "heuristic", "a", "easy", 0, 1.0, tokens=False)
    md = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v1"]).read_text(encoding="utf-8")
    sec = md.split("## Step limit")[1].split("\n## ")[0]
    # 4 fault runs (the control is left out); 3 hit the 15-step limit; of those 2 said no incident, 1 was right
    assert "| agent-v1 | 4 | 3 (75%) | 2 of 3 | 0.33 | 1.00 |" in sec
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

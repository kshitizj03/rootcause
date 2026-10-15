import json

import pytest

from rootcause import config, scenarios, site


def _scn(sid, category, causes):
    return scenarios.Scenario(id=sid, category=category, alert=f"alert for {sid}", inject={},
                              truth={"causes": causes}, checks=[])


def _rec(solver, sid, run, correct, **extra):
    rec = {"solver": solver, "scenario": sid, "category": "easy" if sid == "a" else "control", "run": run,
           "code": "abc123", "messages": "SECRET", "path": "snapshots/incident__x",
           "report": {"verdict": "incident", "causes": [{"service": "ad", "fault_type": "errors"}],
                      "evidence": ["e0", "e1"], "confidence": 0.9},
           "score": {"correct": correct, "top3": True, "fault_type_ok": True, "false_alarm": False, "abstained": False}}
    rec.update(extra)
    return rec


def _walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _setup(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    (runs / "heuristic").mkdir(parents=True)
    (runs / "agent-v1").mkdir()
    heur = _rec("heuristic", "a", 0, 1.0, report={
        "verdict": "incident", "causes": [{"service": "ad", "fault_type": "errors"}],
        "evidence": [{"kind": "metric", "claim": "x"}], "confidence": 0.7},
        evidence_check={"items": [{"grounded": True, "distinctive": False}]})
    huge = json.dumps({"rows": "x" * 5000})
    steps = [{"tool": "list_services", "args": "{}", "output": '{"services": ["ad"]}'},
             {"tool": "get_logs", "args": '{"service":"ad"}', "output": huge}]
    a0 = _rec("agent-v1", "a", 0, 1.0, transcript=steps, requests=3, prompt_tokens=10, completion_tokens=5,
              parse_error=None, error=None, evidence_check={"items": [{"grounded": True, "distinctive": True}]})
    a1 = _rec("agent-v1", "a", 1, 0.0, transcript=[])
    for solver, rec in (("heuristic", heur), ("agent-v1", a0), ("agent-v1", a1)):
        (runs / solver / f"a__{rec['run']}.json").write_text(json.dumps(rec), encoding="utf-8")
    snap = tmp_path / "snaps" / "incident__1"
    snap.mkdir(parents=True)
    # the snapshot truth wins over the YAML truth (which says "cart")
    (snap / "truth.json").write_text(json.dumps({"causes": [{"accept": ["ad"], "fault_type": "errors"}]}), encoding="utf-8")
    (tmp_path / "snaps" / "index.jsonl").write_text(json.dumps({"scenario": "a", "path": str(snap)}) + "\n", encoding="utf-8")
    fig = tmp_path / "docs" / "results" / "figures"
    fig.mkdir(parents=True)
    (fig / "f.png").write_bytes(b"png")
    monkeypatch.setattr(config, "SNAPSHOTS", tmp_path / "snaps")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    monkeypatch.setattr(scenarios, "load_all", lambda: [_scn("a", "easy", [{"accept": ["cart"], "fault_type": "errors"}]),
                                                         _scn("b", "control", [])])
    return runs


def test_build_writes_index_and_incidents_without_private_fields(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch)
    out = site.build(tmp_path / "out", runs, ["heuristic", "agent-v1", "agent-v0"])
    index = json.loads((out / "data" / "index.json").read_text(encoding="utf-8"))
    assert index["solvers"] == ["heuristic", "agent-v1"] and index["categories"] == ["easy", "control"]
    a, b = index["incidents"]
    assert a["results"]["agent-v1"] == [1.0, 0.0] and a["results"]["heuristic"] == [1.0]
    assert (a["heldout"], b["heldout"]) == (False, True) and b["truth"] == [] and b["results"] == {}
    assert a["truth"] == [{"accept": ["ad"], "fault_type": "errors"}]
    assert index["summary"]["agent-v1"][0]["category"] == "easy"
    assert index["planned_runs"] == {"heuristic": 1, "agent-v1": 5}  # solvers with records only

    inc = json.loads((out / "data" / "incidents" / "a.json").read_text(encoding="utf-8"))
    run0, run1 = inc["runs"]["agent-v1"]
    assert inc["window_end_s"] == config.SETTLE_S
    assert inc["runs"]["heuristic"][0]["steps"] == []
    assert run0["steps"][0] == {"tool": "list_services", "args": {}, "output": {"services": ["ad"]}, "truncated": False}
    assert run0["steps"][1]["args"] == {"service": "ad"}
    assert len(run0["steps"][1]["output"]) == 3000 and run0["steps"][1]["truncated"] is True
    assert run0["evidence"][0] == {"item": "e0", "grounded": True, "distinctive": True}
    assert run0["evidence"][1] == {"item": "e1", "grounded": None, "distinctive": None}
    assert run1["evidence"][0]["grounded"] is None and run0["requests"] == 3
    assert (out / "figures" / "f.png").read_bytes() == b"png"

    for f in (out / "data").rglob("*.json"):
        assert not {"messages", "path", "code"} & set(_walk(json.loads(f.read_text(encoding="utf-8")))), f


def test_build_removes_stale_outputs_but_keeps_other_files(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch)
    out = tmp_path / "out"
    for stale in ("data/incidents/gone.json", "figures/gone.png"):
        (out / stale).parent.mkdir(parents=True, exist_ok=True)
        (out / stale).write_bytes(b"old")
    (out / "index.html").write_text("page", encoding="utf-8")
    site.build(out, runs)
    assert not (out / "data" / "incidents" / "gone.json").exists() and not (out / "figures" / "gone.png").exists()
    assert (out / "data" / "incidents" / "a.json").exists() and (out / "figures" / "f.png").exists()
    assert (out / "index.html").read_text(encoding="utf-8") == "page"  # only data/ and figures/ are generated


def test_build_is_deterministic(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch)
    one, two = site.build(tmp_path / "one", runs), site.build(tmp_path / "two", runs)
    read = lambda d, p: json.loads((d / p).read_text(encoding="utf-8"))
    for p in ("data/incidents/a.json", "data/incidents/b.json"):
        assert (one / p).read_bytes() == (two / p).read_bytes()
    i1, i2 = read(one, "data/index.json"), read(two, "data/index.json")
    i1.pop("generated"), i2.pop("generated")
    assert i1 == i2


def test_cli_site_prints_output_path(monkeypatch, capsys):
    from rootcause import cli
    monkeypatch.setattr(site, "build", lambda: "OUT/site")
    assert cli.main(["site"]) == 0
    assert capsys.readouterr().out.strip() == "OUT/site"


def test_build_refuses_to_delete_run_data(tmp_path):
    for bad in (config.ROOT, config.DATA, config.ROOT.parent, config.ROOT / "docs" / "results", config.DATA / "runs"):
        with pytest.raises(ValueError):
            site.build(out_dir=bad, runs_dir=tmp_path)


def test_long_json_outputs_are_shortened_by_cutting_lists_so_they_still_parse():
    spans = [{"service": "cart", "name": "op", "t": i, "dur_ms": 1.5, "error": False, "message": "m" * 40} for i in range(200)]
    step = site._step({"tool": "get_trace", "args": "{}", "output": json.dumps({"trace_id": "abc", "spans": spans})})
    out = step["output"]
    assert step["truncated"] is True and isinstance(out, dict)  # still structured, so the page renders a table
    assert out["trace_id"] == "abc" and out["spans"] == spans[:len(out["spans"])] and 0 < len(out["spans"]) < 200
    assert out["_trimmed"] == {"spans": 200} and len(json.dumps(out)) <= site.MAX_OUTPUT
    # one list item that alone is too long cannot be cut further: falls back to plain-text truncation
    big = site._step({"tool": "search_logs", "args": "{}", "output": json.dumps({"samples": ["x" * 5000]})})
    assert big["truncated"] is True and isinstance(big["output"], str) and len(big["output"]) == site.MAX_OUTPUT
    # log samples are the last N lines, so the newest ones are kept
    logs = [{"t": i, "severity": "INFO", "body": "b" * 300} for i in range(20)]
    cut = site._step({"tool": "search_logs", "args": "{}", "output": json.dumps({"service": "a", "total": 99, "samples": logs})})["output"]
    assert cut["_trimmed"] == {"samples": 20} and cut["samples"] == logs[-len(cut["samples"]):]


def test_outputs_the_tool_cut_for_the_agent_are_repaired_at_the_last_whole_item():
    from rootcause import tools_v0 as tools
    text = json.dumps({"trace_id": "abc", "spans": [{"t": i, "name": "op" * 30} for i in range(100)]})[:5000] + tools.TRUNCATED
    step = site._step({"tool": "get_trace", "args": "{}", "output": text})
    out = step["output"]
    assert step["truncated"] is True and isinstance(out, dict) and out["_cut_by_tool"] is True
    assert out["trace_id"] == "abc" and [s["t"] for s in out["spans"]] == list(range(len(out["spans"])))
    assert len(json.dumps(out)) <= site.MAX_OUTPUT
    # garbage that only looks cut stays text
    junk = site._step({"tool": "get_trace", "args": "{}", "output": "{x" * 3000 + tools.TRUNCATED})
    assert isinstance(junk["output"], str)

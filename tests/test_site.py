import json

from rootcause import config, scenarios, site


def _scn(sid, category, causes):
    return scenarios.Scenario(id=sid, category=category, alert=f"alert for {sid}", inject={},
                              truth={"causes": causes}, checks=[])


def _rec(solver, sid, run, correct, **extra):
    rec = {"solver": solver, "scenario": sid, "category": "easy" if sid == "a" else "control", "run": run,
           "code": "abc123", "messages": "SECRET", "path": "D:/x",
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


def test_build(tmp_path, monkeypatch):
    runs = _setup(tmp_path, monkeypatch)
    out = site.build(tmp_path / "out", runs, ["heuristic", "agent-v1", "agent-v0"])
    index = json.loads((out / "data" / "index.json").read_text(encoding="utf-8"))
    assert index["solvers"] == ["heuristic", "agent-v1"] and index["categories"] == ["easy", "control"]
    a, b = index["incidents"]
    assert a["results"]["agent-v1"] == [1.0, 0.0] and a["results"]["heuristic"] == [1.0]
    assert (a["heldout"], b["heldout"]) == (False, True) and b["truth"] == [] and b["results"] == {}
    assert a["truth"] == [{"accept": ["ad"], "fault_type": "errors"}]
    assert index["summary"]["agent-v1"][0]["category"] == "easy"

    inc = json.loads((out / "data" / "incidents" / "a.json").read_text(encoding="utf-8"))
    run0, run1 = inc["runs"]["agent-v1"]
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

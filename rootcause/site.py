"""Build the JSON behind the static replay site (site/data/) from recorded run records.

Post-hoc only: it shows ground truth, so nothing else in rootcause/ may import it. Run records are copied through an
allow-list of fields (never `messages`, `code` or paths), and tool outputs are cut to MAX_OUTPUT characters."""
import json
import shutil
from datetime import date
from pathlib import Path

from rootcause import config, evaluate, report, scenarios, snapshot

MAX_OUTPUT = 3000


def _dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=None, separators=(",", ":")), encoding="utf-8")


def _parse(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _step(t):
    out = t.get("output", "")
    out = out if isinstance(out, str) else json.dumps(out)
    cut = len(out) > MAX_OUTPUT  # a cut JSON text no longer parses, so it is shown as text
    return {"tool": t["tool"], "args": _parse(t.get("args")), "output": out[:MAX_OUTPUT] if cut else _parse(out),
            "truncated": cut}


def _run(r):
    rep, checks = r["report"], (r.get("evidence_check") or {}).get("items") or []
    evidence = [{"item": item, "grounded": checks[i].get("grounded") if i < len(checks) else None,
                 "distinctive": checks[i].get("distinctive") if i < len(checks) else None}
                for i, item in enumerate(rep.get("evidence") or [])]
    return {"run": r["run"], "verdict": rep["verdict"], "causes": rep.get("causes") or [],
            "confidence": rep.get("confidence"), "score": r["score"], "evidence": evidence,
            "steps": [_step(t) for t in r.get("transcript") or []],
            **{k: r.get(k) for k in ("requests", "prompt_tokens", "completion_tokens", "parse_error", "error")}}


def _truth(s, rows):
    """Latest snapshot's truth.json; the scenario YAML if it has no snapshot (or the snapshot dir is gone)."""
    try:
        truth = snapshot.load_truth(rows[s.id]["path"]) if s.id in rows else s.truth
    except OSError:
        truth = s.truth
    return [{"accept": c["accept"], "fault_type": c["fault_type"]} for c in truth.get("causes", [])]


def build(out_dir=config.ROOT / "site", runs_dir=evaluate.RUNS_DIR, solvers=report.SOLVER_ORDER):
    """Write out_dir/data/index.json, out_dir/data/incidents/<id>.json and out_dir/figures/*.png; return out_dir."""
    out_dir = Path(out_dir)
    if out_dir.resolve() in (config.ROOT.resolve(), config.DATA.resolve()) or out_dir.resolve() in config.ROOT.resolve().parents:
        raise ValueError(f"refusing to build the site into {out_dir}: it would delete run data")  # data/ holds days of runs
    for generated in ("data", "figures"):  # drop outputs of scenarios/figures that no longer exist
        shutil.rmtree(out_dir / generated, ignore_errors=True)
    lib = scenarios.load_all()
    rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", [s.id for s in lib])
    records = {n: evaluate.load_records(n, runs_dir) for n in solvers}
    records = {n: rs for n, rs in records.items() if rs}
    incidents = []
    for s in lib:
        runs = {n: [_run(r) for r in sorted(rs, key=lambda r: r["run"]) if r["scenario"] == s.id]
                for n, rs in records.items()}
        runs = {n: v for n, v in runs.items() if v}
        meta = {"id": s.id, "category": s.category, "heldout": s.id in config.HELDOUT, "alert": s.alert,
                "truth": _truth(s, rows)}
        _dump(out_dir / "data" / "incidents" / f"{s.id}.json", {**meta, "runs": runs})
        incidents.append({**meta, "results": {n: [r["score"]["correct"] for r in v] for n, v in runs.items()}})
    expected = evaluate.expected_counts("all")
    index = {"generated": date.today().isoformat(), "solvers": list(records), "incidents": incidents,
             "categories": [c for c in evaluate.ORDER if c in {s.category for s in lib}],
             "summary": {n: evaluate.summarise(n, runs_dir, expected=expected, split="all") for n in records}}
    _dump(out_dir / "data" / "index.json", index)
    for png in sorted((config.ROOT / "docs" / "results" / "figures").glob("*.png")):
        (out_dir / "figures").mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, out_dir / "figures" / png.name)
    return out_dir

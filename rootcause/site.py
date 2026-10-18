"""Build the JSON behind the static replay site (site/data/) from recorded run records.

Post-hoc only: it shows ground truth, so no solver or evaluation code may import it (only the CLI). Run records are copied through an
allow-list of fields (never `messages`, `code` or paths), and tool outputs are cut to MAX_OUTPUT characters (by
halving their longest lists while that is enough, so they still parse; as plain text otherwise)."""
import json
import shutil
from datetime import date
from pathlib import Path

from rootcause import config, evaluate, report, scenarios, snapshot, tools_v0

MAX_OUTPUT = 3000
TAIL_LISTS = {"samples"}  # search_logs returns the *last* N lines, so cutting keeps the newest
ALERT_PROMPT = "ALERT (fired at t=0): "  # agent._solve's first user message


def _dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=None, separators=(",", ":")), encoding="utf-8")


def _parse(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _shrink(obj):
    """Halve the longest list in a JSON object until it fits MAX_OUTPUT, so the page can still render it as a table;
    `_trimmed` records each cut list's original length. None when cutting lists cannot make it fit."""
    if not isinstance(obj, dict):
        return None
    obj, trimmed = dict(obj), {}
    while len(json.dumps(obj)) > MAX_OUTPUT:
        lists = [k for k, v in obj.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            return None
        k = max(lists, key=lambda k: len(json.dumps(obj[k])))
        trimmed.setdefault(k, len(obj[k]))
        half = len(obj[k]) // 2
        obj[k] = obj[k][-half:] if k in TAIL_LISTS else obj[k][:half]
        obj["_trimmed"] = trimmed
    return obj


def _repair(text):
    """An output the tool itself cut for the agent (tools_v0.TRUNCATED) is JSON cut mid-list: close it after the last
    whole item. None when that does not give an object."""
    if not text.endswith(tools_v0.TRUNCATED):
        return None
    head = text[:-len(tools_v0.TRUNCATED)]
    end = head.rfind("}, {")
    fixed = _parse(head[:end + 1] + "]}") if end > 0 else None
    return {**fixed, "_cut_by_tool": True} if isinstance(fixed, dict) else None


def _step(t):
    out = t.get("output", "")
    out = out if isinstance(out, str) else json.dumps(out)
    if len(out) <= MAX_OUTPUT:
        return {"tool": t["tool"], "args": _parse(t.get("args")), "output": _parse(out), "truncated": False}
    parsed = _parse(out)
    shrunk = _shrink(_repair(out) if isinstance(parsed, str) else parsed)  # a cut JSON text no longer parses, so cut lists first and the text only as a fallback
    return {"tool": t["tool"], "args": _parse(t.get("args")), "output": shrunk if shrunk is not None else out[:MAX_OUTPUT],
            "truncated": True}


def _run(r):
    rep, checks = r["report"], (r.get("evidence_check") or {}).get("items") or []
    evidence = [{"item": item, "grounded": checks[i].get("grounded") if i < len(checks) else None,
                 "distinctive": checks[i].get("distinctive") if i < len(checks) else None}
                for i, item in enumerate(rep.get("evidence") or [])]
    return {"run": r["run"], "verdict": rep["verdict"], "causes": rep.get("causes") or [],
            "confidence": rep.get("confidence"), "score": r["score"], "evidence": evidence,
            "steps": [_step(t) for t in r.get("transcript") or []],
            **{k: r.get(k) for k in ("requests", "prompt_tokens", "completion_tokens", "parse_error", "error")}}


def _alert_shown(rs):
    """The alert a solver's first stored run was shown, read from its first user message; None for a solver that stores
    no messages (the heuristic, most custom solvers), which is given the scenario's own alert."""
    msgs = rs[0].get("messages") if rs else None
    for m in msgs if isinstance(msgs, list) else []:
        if isinstance(m, dict) and m.get("role") == "user" and str(m.get("content", "")).startswith(ALERT_PROMPT):
            return m["content"][len(ALERT_PROMPT):]
    return None


def _pair(a, b, p, every):
    keep = lambda q: {"n": q["n"], "mean_diff": q["mean_diff"], "ci": q["ci"]}
    return {"a": a, "b": b, **keep(p), "with_controls": keep(every)}


def _truth(s, rows):
    """Latest snapshot's truth.json; the scenario YAML if it has no snapshot (or the snapshot dir is gone)."""
    try:
        truth = snapshot.load_truth(rows[s.id]["path"]) if s.id in rows else s.truth
    except OSError:
        truth = s.truth
    return [{"accept": c["accept"], "fault_type": c["fault_type"]} for c in truth.get("causes", [])]


def build(out_dir=config.ROOT / "site", runs_dir=evaluate.RUNS_DIR, solvers=None):
    """Write out_dir/data/index.json, out_dir/data/incidents/<id>.json and out_dir/figures/*.png; return out_dir.
    solvers: default evaluate.listed_solvers (the built-in ones, then any other with records). evaluate.EXPERIMENT_SOLVERS
    are always left out: they are not agents, so they are not on the scoreboard or the incident pages."""
    solvers = [s for s in (evaluate.listed_solvers(runs_dir) if solvers is None else solvers)
               if s not in evaluate.EXPERIMENT_SOLVERS]
    out_dir = Path(out_dir)
    target, root = out_dir.resolve(), config.ROOT.resolve()
    protected = (config.DATA.resolve(), (root / "docs" / "results" / "figures").resolve())  # run records, source figures
    # a build deletes target/data and target/figures: never at or above the repo root, nor at, in or above a protected dir
    if root.is_relative_to(target) or any(target.is_relative_to(p) or p.is_relative_to(target) for p in protected):
        raise ValueError(f"refusing to build the site into {out_dir}: it would delete run data")  # data/ holds days of runs
    for generated in ("data", "figures"):  # drop outputs of scenarios/figures that no longer exist
        shutil.rmtree(out_dir / generated, ignore_errors=True)
    lib = scenarios.load_all()
    rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", [s.id for s in lib], valid_only=True)
    records = {n: evaluate.load_records(n, runs_dir) for n in solvers}
    records = {n: rs for n, rs in records.items() if rs}
    incidents = []
    for s in lib:
        runs = {n: [_run(r) for r in sorted(rs, key=lambda r: r["run"]) if r["scenario"] == s.id]
                for n, rs in records.items()}
        runs = {n: v for n, v in runs.items() if v}
        meta = {"id": s.id, "category": s.category, "heldout": s.id in config.HELDOUT,
                "heldout_viewed": s.id == config.HELDOUT_VIEWED, "alert": s.alert, "truth": _truth(s, rows)}
        # solvers shown another alert than the scenario's (the vague-alert ablations), from what their runs were sent
        shown = {n: a for n, rs in records.items()
                 if (a := _alert_shown([r for r in rs if r["scenario"] == s.id])) is not None and a != s.alert}
        _dump(out_dir / "data" / "incidents" / f"{s.id}.json",
              {**meta, "runs": runs, "alerts_shown": shown, "window_end_s": s.settle_s})
        incidents.append({**meta, "results": {n: [r["score"]["correct"] for r in v] for n, v in runs.items()}})
    expected = evaluate.expected_counts("all")
    index = {"generated": date.today().isoformat(), "solvers": list(records), "incidents": incidents,
             "planned_runs": {n: evaluate.planned_runs(n) for n in records},
             "categories": [c for c in evaluate.ORDER if c in {s.category for s in lib}],
             "summary": {n: evaluate.summarise(n, runs_dir, expected=expected, split="all") for n in records},
             "paired": [_pair(*r) for r in report.paired_results(records)],
             # accuracy vs coverage as the confidence threshold rises (evaluate.coverage_curve), for solvers that state one
             "coverage": {n: [{k: round(p[k], 4) for k in ("threshold", "coverage", "accuracy")}
                              for p in evaluate.coverage_curve(rs)] for n, rs in records.items()
                          if any(evaluate.confidence(r) is not None for r in rs)}}
    _dump(out_dir / "data" / "index.json", index)
    for png in sorted((config.ROOT / "docs" / "results" / "figures").glob("*.png")):
        (out_dir / "figures").mkdir(parents=True, exist_ok=True)
        shutil.copy2(png, out_dir / "figures" / png.name)
    return out_dir

"""Capture an incident's telemetry into a self-contained, sanitised snapshot directory; load it back."""
import gzip
import json
import os
import time
from pathlib import Path

from rootcause import backends, config, sanitize, signals, summary


def _write_jsonl_gz(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _dedupe_logs(logs):
    """Drop exact duplicates (same ts, service, body, severity, trace_id); the first one stays."""
    seen, out = set(), []
    for lg in logs:
        key = tuple(lg.get(k) for k in ("ts", "service", "body", "severity", "trace_id"))
        if key not in seen:
            seen.add(key)
            out.append(lg)
    return out


def latest_rows(index_path, scenario_ids=None):
    """{scenario id: newest index.jsonl row that has a path}; rows without a path (failed captures) are skipped.
    scenario_ids, if given, restricts the result to those ids. A missing index gives {}."""
    index = Path(index_path)
    rows = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l.strip()] if index.exists() else []
    latest = {r["scenario"]: r for r in rows if r.get("path")}  # later rows overwrite earlier ones
    return latest if scenario_ids is None else {i: latest[i] for i in scenario_ids if i in latest}


def capture(scenario, t_inject, t_end, names, fetch=backends, out_dir=config.SNAPSHOTS, demo_commit=""):
    baseline_start = t_inject - config.BASELINE_S
    metrics = signals.fetch_series(fetch.prom_range, baseline_start, t_end, config.STEP_S)

    # Backends return newest-first and cap per call, so a chatty service would fill the cap with
    # post-fault items only. Fetch pre-fault and fault windows separately, each with the full cap.
    windows = [(t_inject - config.CAPTURE_LOOKBACK_S, t_inject), (t_inject, t_end)]
    spans, seen = [], set()
    for service in config.APP_SERVICES:
        for start, end in windows:
            for sp in backends.flatten_otlp(fetch.jaeger_raw(service, start, end, config.TRACES_PER_SERVICE)):
                if sp["span_id"] not in seen:
                    seen.add(sp["span_id"])
                    spans.append(sp)
    logs = []  # no natural log key; windows don't overlap, so just concatenate
    for service in config.KNOWN_TARGETS:
        query = f'resource.service.name:"{service}"'
        for start, end in windows:
            rows = (backends.flatten_log(src) for src in fetch.os_logs(query, start, end, config.LOGS_PER_SERVICE))
            logs += [r for r in rows if r["service"] == service]  # the query also matches e.g. frontend-proxy
    logs = _dedupe_logs(logs)  # some services (recommendation) emit every line twice

    spans, logs = sanitize.sanitize_spans(spans, names), sanitize.sanitize_logs(logs, names)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(t_inject))
    path = Path(out_dir) / f"incident__{stamp}"
    path.mkdir(parents=True)
    meta = {"alert": scenario.alert, "baseline_start": baseline_start, "fault_start": t_inject,
            "end": t_end, "demo_commit": demo_commit}
    (path / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    truth = dict(scenario.truth, scenario_id=scenario.id, category=scenario.category)
    (path / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    (path / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    _write_jsonl_gz(path / "spans.jsonl.gz", spans)
    _write_jsonl_gz(path / "logs.jsonl.gz", logs)

    result = validate_snapshot(path, scenario, names)
    return {"scenario": scenario.id, "path": str(path), **result}


def resanitize(path, names, dry_run=False):
    """Re-apply the CURRENT sanitisers to a recorded snapshot's spans and logs (idempotent filters).

    Both files are read and filtered before anything is written, then swapped in via .tmp + os.replace,
    so a failure before the swap leaves the originals untouched. metrics.json only loses series of hidden/unknown
    services (kept series untouched, rewritten only if something was dropped); meta/truth are never touched.
    Returns {"spans": (before, after), "logs": (before, after), "metrics": (series before, after),
    "dropped": {"spans": [...], "logs": [...]}};
    "dropped" is only filled for dry_run."""
    path, counts, dropped, kept = Path(path), {}, {}, {}
    if not dry_run:  # leftovers of a hard-killed run must never be promoted
        for stale in ("spans.jsonl.gz.tmp", "logs.jsonl.gz.tmp", "metrics.json.tmp"):
            (path / stale).unlink(missing_ok=True)
    for name, clean in (("spans", sanitize.sanitize_spans), ("logs", sanitize.sanitize_logs)):
        rows = _read_jsonl_gz(path / f"{name}.jsonl.gz")
        kept[name] = _dedupe_logs(clean(rows, names)) if name == "logs" else clean(rows, names)
        counts[name] = (len(rows), len(kept[name]))
        # ponytail: per-row re-run to find what was dropped (rebuilds the pattern each row); dry-run only
        dropped[name] = [r for r in rows if not clean([r], names)] if dry_run else []
    metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8")) if (path / "metrics.json").exists() else {}
    clean_metrics = sanitize.sanitize_metrics(metrics)
    count = lambda m: sum(len(v) for v in m.values())
    counts["metrics"] = (count(metrics), count(clean_metrics))
    changed = counts["metrics"][0] != counts["metrics"][1]
    if not dry_run:
        tmps = {n: path / f"{n}.jsonl.gz.tmp" for n in kept}
        mtmp = path / "metrics.json.tmp"
        try:
            for n, tmp in tmps.items():
                _write_jsonl_gz(tmp, kept[n])
            if changed:
                mtmp.write_text(json.dumps(clean_metrics), encoding="utf-8")
            for n, tmp in tmps.items():
                os.replace(tmp, path / f"{n}.jsonl.gz")
            if changed:
                os.replace(mtmp, path / "metrics.json")
        finally:
            for tmp in (*tmps.values(), mtmp):
                tmp.unlink(missing_ok=True)
    return {**counts, "dropped": dropped}


def validate_snapshot(path, scenario, names):
    """Score a recorded snapshot against the scenario's CURRENT checks; rewrites validation.json."""
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    results = signals.evaluate(scenario.checks, metrics, *summary.windows(meta))
    leaks = sanitize.scan_snapshot(path, names)
    out = {"valid": all(r["passed"] for r in results) and not leaks, "results": results, "leaks": leaks}
    (path / "validation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def load(path):
    """Load what an agent may see: meta.json plus sanitize.SNAPSHOT_TOOL_FILES (metrics, spans, logs) and nothing else.
    Agent tools may read ONLY those. validation.json, truth.json, index.jsonl and the repository (scenarios/,
    NOTES.md) name the answer and must never be exposed."""
    path = Path(path)
    return {"meta": json.loads((path / "meta.json").read_text(encoding="utf-8")),
            "metrics": json.loads((path / "metrics.json").read_text(encoding="utf-8")),
            "spans": _read_jsonl_gz(path / "spans.jsonl.gz"),
            "logs": _read_jsonl_gz(path / "logs.jsonl.gz")}


def load_truth(path):
    return json.loads((Path(path) / "truth.json").read_text(encoding="utf-8"))

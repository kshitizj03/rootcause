"""Capture an incident's telemetry into a self-contained, sanitised snapshot directory; load it back."""
import gzip
import json
import os
import time
from pathlib import Path

from rootcause import backends, config, sanitize, signals


def _write_jsonl_gz(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _read_jsonl_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


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
            logs += [backends.flatten_log(src) for src in fetch.os_logs(query, start, end, config.LOGS_PER_SERVICE)]

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
    so a failure before the swap leaves the originals untouched. metrics/meta/truth are never touched.
    Returns {"spans": (before, after), "logs": (before, after), "dropped": {"spans": [...], "logs": [...]}};
    "dropped" is only filled for dry_run."""
    path, counts, dropped, kept = Path(path), {}, {}, {}
    for name, clean in (("spans", sanitize.sanitize_spans), ("logs", sanitize.sanitize_logs)):
        rows = _read_jsonl_gz(path / f"{name}.jsonl.gz")
        kept[name] = clean(rows, names)
        counts[name] = (len(rows), len(kept[name]))
        # ponytail: per-row re-run to find what was dropped (rebuilds the pattern each row); dry-run only
        dropped[name] = [r for r in rows if not clean([r], names)] if dry_run else []
    if not dry_run:
        tmps = {n: path / f"{n}.jsonl.gz.tmp" for n in kept}
        try:
            for n, tmp in tmps.items():
                _write_jsonl_gz(tmp, kept[n])
            for n, tmp in tmps.items():
                os.replace(tmp, path / f"{n}.jsonl.gz")
        finally:
            for tmp in tmps.values():
                tmp.unlink(missing_ok=True)
    return {**counts, "dropped": dropped}


def validate_snapshot(path, scenario, names):
    """Score a recorded snapshot against the scenario's CURRENT checks; rewrites validation.json."""
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    results = signals.evaluate(scenario.checks, metrics, (meta["baseline_start"], meta["fault_start"]),
                               (meta["fault_start"] + config.RAMP_S, meta["end"]))
    leaks = sanitize.scan_snapshot(path, names)
    out = {"valid": all(r["passed"] for r in results) and not leaks, "results": results, "leaks": leaks}
    (path / "validation.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def load(path):
    path = Path(path)
    return {"meta": json.loads((path / "meta.json").read_text(encoding="utf-8")),
            "metrics": json.loads((path / "metrics.json").read_text(encoding="utf-8")),
            "spans": _read_jsonl_gz(path / "spans.jsonl.gz"),
            "logs": _read_jsonl_gz(path / "logs.jsonl.gz")}


def load_truth(path):
    return json.loads((Path(path) / "truth.json").read_text(encoding="utf-8"))

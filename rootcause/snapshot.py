"""Capture an incident's telemetry into a self-contained, sanitised snapshot directory; load it back."""
import gzip
import json
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

    since = t_inject - config.CAPTURE_LOOKBACK_S
    spans, seen = [], set()
    for service in config.APP_SERVICES:
        for sp in backends.flatten_otlp(fetch.jaeger_raw(service, since, t_end, config.TRACES_PER_SERVICE)):
            if sp["span_id"] not in seen:
                seen.add(sp["span_id"])
                spans.append(sp)
    logs = []
    for service in config.KNOWN_TARGETS:
        query = f'resource.service.name:"{service}"'
        logs += [backends.flatten_log(src) for src in fetch.os_logs(query, since, t_end, config.LOGS_PER_SERVICE)]

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

    results = signals.evaluate(scenario.checks, metrics, (baseline_start, t_inject), (t_inject + config.RAMP_S, t_end))
    leaks = sanitize.scan_snapshot(path, names)
    valid = all(r["passed"] for r in results) and not leaks
    (path / "validation.json").write_text(json.dumps({"valid": valid, "results": results, "leaks": leaks}, indent=1), encoding="utf-8")
    return {"scenario": scenario.id, "path": str(path), "valid": valid, "results": results, "leaks": leaks}


def load(path):
    path = Path(path)
    return {"meta": json.loads((path / "meta.json").read_text(encoding="utf-8")),
            "metrics": json.loads((path / "metrics.json").read_text(encoding="utf-8")),
            "spans": _read_jsonl_gz(path / "spans.jsonl.gz"),
            "logs": _read_jsonl_gz(path / "logs.jsonl.gz")}


def load_truth(path):
    return json.loads((Path(path) / "truth.json").read_text(encoding="utf-8"))

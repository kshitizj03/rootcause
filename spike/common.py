"""Shared helpers for the feasibility spike: query the demo's telemetry backends and flip fault flags."""
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "vendor/opentelemetry-demo"
FLAGS = DEMO / "src/flagd/demo.flagd.json"
FLAGS_BACKUP = ROOT / "spike/demo.flagd.json.orig"

PROM = "http://localhost:9090"
JAEGER = "http://localhost:16686/jaeger/ui/api/v3"  # Jaeger v2 only serves the v3 API (OTLP JSON)
OPENSEARCH = "http://localhost:9200"


def prom(query):
    r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=20)
    r.raise_for_status()
    return r.json()["data"]["result"]


def jaeger_services():
    return requests.get(f"{JAEGER}/services", timeout=20).json().get("services", [])


def jaeger_traces(service, lookback_min=5, limit=50, errors_only=False):
    """Recent spans for a service, flattened from OTLP JSON: [{trace_id, service, name, ms, error, message}]."""
    now = datetime.now(timezone.utc)
    params = {"query.service_name": service, "query.num_traces": limit,
              "query.start_time_min": (now - timedelta(minutes=lookback_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "query.start_time_max": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    r = requests.get(f"{JAEGER}/traces", params=params, timeout=60)
    if r.status_code == 404:  # v3 API returns 404 when no traces match
        return []
    r.raise_for_status()
    spans = []
    for rs in r.json()["result"]["resourceSpans"]:
        svc = next((a["value"].get("stringValue") for a in rs["resource"]["attributes"] if a["key"] == "service.name"), "?")
        for ss in rs["scopeSpans"]:
            for sp in ss["spans"]:
                st = sp.get("status", {})
                err = st.get("code") in (2, "STATUS_CODE_ERROR")
                if errors_only and not err:
                    continue
                spans.append({"trace_id": sp["traceId"], "service": svc, "name": sp["name"], "error": err,
                              "message": st.get("message", ""),
                              "ms": (int(sp["endTimeUnixNano"]) - int(sp["startTimeUnixNano"])) / 1e6})
    return spans


def logs(query, minutes=5, size=20):
    body = {"size": size, "sort": [{"@timestamp": "desc"}],
            "query": {"bool": {"must": [{"query_string": {"query": query}}],
                               "filter": [{"range": {"@timestamp": {"gte": f"now-{minutes}m"}}}]}}}
    r = requests.post(f"{OPENSEARCH}/otel-logs-*/_search", json=body, timeout=30)
    r.raise_for_status()
    return r.json()["hits"]


def set_flag(name, variant):
    """Flip a flag by editing the file flagd watches. Keeps a pristine backup on first use."""
    if not FLAGS_BACKUP.exists():
        shutil.copy(FLAGS, FLAGS_BACKUP)
    cfg = json.loads(FLAGS.read_text())
    assert variant in cfg["flags"][name]["variants"], f"{name} has no variant {variant!r}"
    cfg["flags"][name]["defaultVariant"] = variant
    FLAGS.write_text(json.dumps(cfg, indent=2))


def reset_flags():
    if FLAGS_BACKUP.exists():
        shutil.copy(FLAGS_BACKUP, FLAGS)


def wait(seconds, label):
    print(f"  ... waiting {seconds}s ({label})", flush=True)
    time.sleep(seconds)

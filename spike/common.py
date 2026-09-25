"""Shared helpers for the feasibility spike: query the demo's telemetry backends and flip fault flags."""
import json
import shutil
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "vendor/opentelemetry-demo"
FLAGS = DEMO / "src/flagd/demo.flagd.json"
FLAGS_BACKUP = ROOT / "spike/demo.flagd.json.orig"

PROM = "http://localhost:9090"
JAEGER = "http://localhost:16686/jaeger/ui/api"
OPENSEARCH = "http://localhost:9200"


def prom(query):
    r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=20)
    r.raise_for_status()
    return r.json()["data"]["result"]


def jaeger_services():
    return requests.get(f"{JAEGER}/services", timeout=20).json()["data"] or []


def jaeger_traces(service, lookback="5m", limit=50, tags=None):
    params = {"service": service, "lookback": lookback, "limit": limit}
    if tags:
        params["tags"] = json.dumps(tags)
    return requests.get(f"{JAEGER}/traces", params=params, timeout=30).json()["data"] or []


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

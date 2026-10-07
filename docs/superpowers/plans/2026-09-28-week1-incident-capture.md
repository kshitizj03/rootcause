# Week 1: Incident Capture Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pipeline that injects a fault into the OpenTelemetry Demo, confirms the fault is visible, and saves a sanitised, leak-free snapshot of the incident's telemetry that later agents and the heuristic replay offline.

**Architecture:** A small Python package `rootcause/` with one module per responsibility: backend HTTP clients, sanitiser/leak finder, fault injector, signal catalog + checks, scenario library, snapshot writer, harness, and CLI. Snapshots are self-contained directories: derived metric series, sanitised spans, sanitised logs, validation, and ground truth. The truth lives in its own file so tools can never read it. Every unit is tested offline with fakes; the live demo is used only in Tasks 9–10.

**Tech Stack:** Python 3.11 (venv at `D:\rootcause\.venv`), requests, PyYAML, pytest; Docker Compose; OpenTelemetry Demo (vendored, commit `cbaf761`); Prometheus / Jaeger v2 (v3 API) / OpenSearch.

## Global Constraints

- Everything (code, data, caches, venv) stays under `D:\rootcause`. `data/` and `vendor/` are gitignored.
- Cost: ₹0. No paid services; no LLM calls in week 1.
- Shell: Git Bash on Windows. Run Python as `.venv/Scripts/python.exe` from `D:\rootcause`.
- Jaeger v2 serves **only** the v3 API at `http://localhost:16686/jaeger/ui/api/v3` (OTLP JSON; 404 = no traces).
- Prometheus metric names verified in the spike: `traces_span_metrics_calls_total{service_name,status_code}`, `traces_span_metrics_duration_milliseconds_bucket`, `container_memory_usage_total_bytes{container_name}`, `container_cpu_usage_nanoseconds_total`, `container_uptime_seconds`.
- OpenSearch logs index `otel-logs-*`; service field `resource.service.name`; severity `severity.text` / `severity.number` (≥17 = ERROR).
- Leak channels that must never reach a snapshot: `feature_flag.*` span attributes/events, the `flagd`/`flagd-ui` services and spans calling flagd, `feature_flag_*` metrics, and log text naming a flag or saying "feature flag".
- Cool-down between injections: 18 minutes (the 15-minute baseline window must be fault-free).
- The flags file `vendor/opentelemetry-demo/src/flagd/demo.flagd.json` must be restored after every run, including on errors.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## File Structure

```
requirements.txt                 deps
pytest.ini                       testpaths + pythonpath
rootcause/__init__.py
rootcause/__main__.py            python -m rootcause → cli.main
rootcause/config.py              paths, endpoints, service lists, timing constants
rootcause/backends.py            HTTP clients (Prometheus range, Jaeger v3, OpenSearch) + pure flatteners
rootcause/sanitize.py            flag names, leak regex, span/log sanitisers, find_leaks, scan_snapshot
rootcause/inject.py              Injector: flag edits + docker pause/cpus, with guaranteed restore
rootcause/signals.py             signal catalog (PromQL), window stats, restarts, check evaluation
rootcause/scenarios.py           Scenario dataclass, YAML loader, validation rules
rootcause/snapshot.py            capture → snapshot dir; load / load_truth
rootcause/harness.py             cool-down, record one, record all (index.jsonl)
rootcause/env.py                 docker compose wrapper, demo commit, stack probe
rootcause/cli.py                 up/down/status/list/reset-flags/record/leak-check
scenarios/*.yaml                 21 scenario definitions (17 incidents + 4 controls)
scenarios/NOTES.md               validation outcomes and decisions (Task 10)
tests/helpers.py                 test builders: OTLP payloads, flat spans, fake clock
tests/fixtures/demo.flagd.json   copy of the pinned demo's flag file (CI has no vendor/)
tests/test_*.py                  one test file per module
```

---

### Task 1: Project scaffold and config

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `rootcause/__init__.py`, `rootcause/config.py`, `tests/helpers.py`, `tests/fixtures/demo.flagd.json`, `tests/test_config.py`

**Interfaces:**
- Produces: `rootcause.config` constants: `ROOT, DEMO, FLAGS_FILE, DATA, SNAPSHOTS, STATE_FILE, SCENARIOS_DIR, COMPOSE_FILES, PROM, JAEGER, OPENSEARCH, APP_SERVICES, HIDDEN_SERVICES, INFRA_CONTAINERS, KNOWN_TARGETS, COOLDOWN_S, BASELINE_S, SETTLE_S, RAMP_S, STEP_S, CAPTURE_LOOKBACK_S, TRACES_PER_SERVICE, LOGS_PER_SERVICE`; test helpers `FLAGS, kv, otlp_payload, flat_span, Clock`.

- [ ] **Step 1: Write requirements, pytest config, package marker**

`requirements.txt`:
```
requests>=2.31
pyyaml>=6.0
python-dotenv>=1.0
openai>=1.50
pytest>=8.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`rootcause/__init__.py`:
```python
"""RootCause: an LLM agent (and baselines) for diagnosing microservice incidents."""
```

- [ ] **Step 2: Install dependencies**

Run: `.venv/Scripts/python.exe -m pip install -q -r requirements.txt && .venv/Scripts/python.exe -c "import yaml, pytest; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Copy the pinned flag file as a test fixture**

Run: `mkdir -p tests/fixtures && cp vendor/opentelemetry-demo/src/flagd/demo.flagd.json tests/fixtures/demo.flagd.json`
(If `vendor/.../demo.flagd.json.orig` exists from an interrupted run, copy that file instead: it is the pristine one.)

- [ ] **Step 4: Write the failing config test**

`tests/test_config.py`:
```python
import json

from helpers import FLAGS
from rootcause import config


def test_known_targets_cover_apps_and_infra_without_hidden():
    assert set(config.APP_SERVICES) <= set(config.KNOWN_TARGETS)
    assert set(config.INFRA_CONTAINERS) <= set(config.KNOWN_TARGETS)
    assert not config.HIDDEN_SERVICES & set(config.KNOWN_TARGETS)


def test_cooldown_covers_baseline():
    assert config.COOLDOWN_S > config.BASELINE_S


def test_fixture_matches_pinned_demo():
    backup = config.FLAGS_FILE.with_name(config.FLAGS_FILE.name + ".orig")
    source = backup if backup.exists() else config.FLAGS_FILE
    if not source.exists():
        import pytest
        pytest.skip("vendored demo not present (CI)")
    assert json.loads(source.read_text()) == json.loads(FLAGS.read_text())
```

- [ ] **Step 5: Write `rootcause/config.py`**

```python
"""Project-wide settings: paths, endpoints, demo compose files, service lists, timing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "vendor" / "opentelemetry-demo"
FLAGS_FILE = DEMO / "src" / "flagd" / "demo.flagd.json"
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
STATE_FILE = DATA / "state.json"
SCENARIOS_DIR = ROOT / "scenarios"

COMPOSE_FILES = ["compose.yaml", "compose.full.yaml", "compose.observability.yaml",
                 "compose.extras.yaml", str(ROOT / "infra" / "compose.ports.yaml")]

PROM = "http://localhost:9090"
JAEGER = "http://localhost:16686/jaeger/ui/api/v3"  # Jaeger v2 serves only the v3 API
OPENSEARCH = "http://localhost:9200"

# Services whose telemetry the agent may see (traced apps).
APP_SERVICES = ["accounting", "ad", "cart", "checkout", "currency", "email", "fraud-detection",
                "frontend", "frontend-proxy", "frontend-web", "image-provider",
                "payment", "product-catalog", "quote", "recommendation", "shipping"]
# The flag service would reveal the injected fault: never shown.
HIDDEN_SERVICES = {"flagd", "flagd-ui", "load-generator"}
# Note (task 10f): load-generator moved here from APP_SERVICES: it is the demo's synthetic users (not observable in
# production) and its flood task names (user_flood_home) reveal that a traffic surge is an artificial decoy.
# Untraced dependencies that still have container metrics and can be a root cause.
INFRA_CONTAINERS = ["kafka", "valkey-cart", "astronomy-db"]
KNOWN_TARGETS = APP_SERVICES + INFRA_CONTAINERS

COOLDOWN_S = 18 * 60        # the 15-minute baseline before an injection must be fault-free
BASELINE_S = 15 * 60
SETTLE_S = 180              # fault runs this long before capture
RAMP_S = 60                 # skip the first minute of the fault when judging its signal
STEP_S = 15                 # metric resolution in snapshots
CAPTURE_LOOKBACK_S = 300    # spans/logs captured from 5 minutes before injection
TRACES_PER_SERVICE = 50
LOGS_PER_SERVICE = 200
```

- [ ] **Step 6: Write `tests/helpers.py`**

```python
"""Builders shared by tests: OTLP payloads, flat spans, a fake clock."""
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
FLAGS = FIXTURES / "demo.flagd.json"


def kv(key, value):
    typ = {bool: "boolValue", int: "intValue", float: "doubleValue"}.get(type(value), "stringValue")
    return {"key": key, "value": {typ: str(value) if typ == "intValue" else value}}


def otlp_payload(service, spans):
    """spans: dicts with span_id, name, optional parent, attrs, events [(name, attrs)], error, message."""
    return {"result": {"resourceSpans": [{
        "resource": {"attributes": [kv("service.name", service)]},
        "scopeSpans": [{"spans": [{
            "traceId": "t1", "spanId": s["span_id"], "parentSpanId": s.get("parent", ""), "name": s["name"],
            "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1250000000",
            "status": {"code": 2, "message": s.get("message", "")} if s.get("error") else {},
            "attributes": [kv(k, v) for k, v in s.get("attrs", {}).items()],
            "events": [{"name": n, "attributes": [kv(k, v) for k, v in a.items()]} for n, a in s.get("events", [])],
        } for s in spans]}],
    }]}}


def flat_span(service="payment", name="charge", attrs=None, events=None, message="", error=False, span_id="s1"):
    return {"trace_id": "t1", "span_id": span_id, "parent_id": "", "service": service, "name": name,
            "start_ms": 1000.0, "dur_ms": 250.0, "error": error, "message": message,
            "attributes": attrs or {}, "events": events or []}


class Clock:
    """Fake time: sleep advances now() and records how long each sleep was."""

    def __init__(self, t=100_000.0):
        self.t = t
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds
```

- [ ] **Step 7: Run tests**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add requirements.txt pytest.ini rootcause tests
git commit -m "Scaffold rootcause package, config and test helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Backend clients and flatteners

**Files:**
- Create: `rootcause/backends.py`, `tests/test_backends.py`

**Interfaces:**
- Consumes: `config.PROM, config.JAEGER, config.OPENSEARCH, config.STEP_S`
- Produces:
  - `prom_range(query: str, start: float, end: float, step: int) -> list[dict]` (Prometheus `result` list)
  - `jaeger_services() -> list[str]`
  - `jaeger_raw(service: str, start: float, end: float, limit: int) -> dict` (OTLP JSON; empty payload on 404)
  - `flatten_otlp(payload: dict) -> list[dict]`: span dicts with keys `trace_id, span_id, parent_id, service, name, start_ms, dur_ms, error, message, attributes, events`
  - `os_logs(query: str, start: float, end: float, size: int) -> list[dict]` (`_source` docs)
  - `flatten_log(src: dict) -> dict`: keys `ts, service, severity, severity_number, body, trace_id`

- [ ] **Step 1: Write the failing tests**

`tests/test_backends.py`:
```python
from helpers import otlp_payload
from rootcause import backends


def test_flatten_otlp_reads_spans_attributes_events_and_errors():
    payload = otlp_payload("payment", [
        {"span_id": "a", "name": "charge", "error": True, "message": "Invalid token",
         "attrs": {"http.status_code": 500, "ok": False, "ratio": 0.5},
         "events": [("exception", {"exception.message": "boom"})]},
        {"span_id": "b", "parent": "a", "name": "db"},
    ])
    spans = backends.flatten_otlp(payload)
    assert [s["span_id"] for s in spans] == ["a", "b"]
    a, b = spans
    assert a["service"] == "payment" and a["error"] is True and a["message"] == "Invalid token"
    assert a["attributes"] == {"http.status_code": 500, "ok": False, "ratio": 0.5}
    assert a["events"] == [{"name": "exception", "attributes": {"exception.message": "boom"}}]
    assert a["start_ms"] == 1000.0 and a["dur_ms"] == 250.0
    assert b["parent_id"] == "a" and b["error"] is False


def test_flatten_otlp_handles_empty_payload():
    assert backends.flatten_otlp({"result": {"resourceSpans": []}}) == []


def test_flatten_log_supports_nested_and_dotted_resource_keys():
    nested = {"@timestamp": "2026-09-28T10:00:00Z", "resource": {"service": {"name": "cart"}},
              "severity": {"text": "ERROR", "number": 17}, "body": "failed", "traceId": "t9"}
    dotted = {"@timestamp": "x", "resource": {"service.name": "email"}, "body": 42}
    assert backends.flatten_log(nested) == {"ts": "2026-09-28T10:00:00Z", "service": "cart", "severity": "ERROR",
                                            "severity_number": 17, "body": "failed", "trace_id": "t9"}
    assert backends.flatten_log(dotted)["service"] == "email"
    assert backends.flatten_log(dotted)["body"] == "42"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -q`
Expected: FAIL: `cannot import name 'backends'`

- [ ] **Step 3: Implement `rootcause/backends.py`**

```python
"""Thin HTTP clients for Prometheus, Jaeger (v3 API) and OpenSearch, plus pure flatteners."""
from datetime import datetime, timezone

import requests

from rootcause import config


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prom_range(query, start, end, step=config.STEP_S):
    r = requests.get(f"{config.PROM}/api/v1/query_range",
                     params={"query": query, "start": start, "end": end, "step": step}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["result"]


def jaeger_services():
    r = requests.get(f"{config.JAEGER}/services", timeout=20)
    r.raise_for_status()
    return r.json().get("services", [])


def jaeger_raw(service, start, end, limit):
    params = {"query.service_name": service, "query.num_traces": limit,
              "query.start_time_min": _iso(start), "query.start_time_max": _iso(end)}
    r = requests.get(f"{config.JAEGER}/traces", params=params, timeout=120)
    if r.status_code == 404:  # the v3 API answers 404 when nothing matches
        return {"result": {"resourceSpans": []}}
    r.raise_for_status()
    return r.json()


def _value(v):
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    return str(v)


def _attrs(kvs):
    return {kv["key"]: _value(kv.get("value", {})) for kv in kvs}


def flatten_otlp(payload):
    """OTLP JSON (Jaeger v3) -> flat span dicts with plain attribute values."""
    out = []
    for rs in payload.get("result", {}).get("resourceSpans", []):
        service = _attrs(rs.get("resource", {}).get("attributes", [])).get("service.name", "?")
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                status = sp.get("status", {})
                start, end = int(sp["startTimeUnixNano"]), int(sp["endTimeUnixNano"])
                out.append({
                    "trace_id": sp["traceId"], "span_id": sp["spanId"], "parent_id": sp.get("parentSpanId", ""),
                    "service": service, "name": sp["name"], "start_ms": start / 1e6, "dur_ms": (end - start) / 1e6,
                    "error": status.get("code") in (2, "STATUS_CODE_ERROR"), "message": status.get("message", ""),
                    "attributes": _attrs(sp.get("attributes", [])),
                    "events": [{"name": e.get("name", ""), "attributes": _attrs(e.get("attributes", []))}
                               for e in sp.get("events", [])],
                })
    return out


def os_logs(query, start, end, size):
    body = {"size": size, "sort": [{"@timestamp": "desc"}],
            "query": {"bool": {"must": [{"query_string": {"query": query}}],
                               "filter": [{"range": {"@timestamp": {"gte": int(start * 1000), "lte": int(end * 1000),
                                                                    "format": "epoch_millis"}}}]}}}
    r = requests.post(f"{config.OPENSEARCH}/otel-logs-*/_search", json=body, timeout=60)
    r.raise_for_status()
    return [h["_source"] for h in r.json()["hits"]["hits"]]


def flatten_log(src):
    res = src.get("resource") or {}
    service = res.get("service.name") or (res.get("service") or {}).get("name") or "?"
    sev = src.get("severity") or {}
    return {"ts": src.get("@timestamp"), "service": service, "severity": sev.get("text"),
            "severity_number": sev.get("number"), "body": str(src.get("body", "")), "trace_id": src.get("traceId", "")}
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backends.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add rootcause/backends.py tests/test_backends.py
git commit -m "Add backend clients and OTLP/log flatteners

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Sanitiser and leak finder

**Files:**
- Create: `rootcause/sanitize.py`, `tests/test_sanitize.py`

**Interfaces:**
- Consumes: flat spans/logs from Task 2 (`flatten_otlp`, `flatten_log` shapes); `config.FLAGS_FILE, config.HIDDEN_SERVICES`
- Produces:
  - `flag_names(flags_file=config.FLAGS_FILE) -> list[str]`
  - `leak_pattern(names) -> re.Pattern`
  - `sanitize_spans(spans: list[dict], names) -> list[dict]`
  - `sanitize_logs(logs: list[dict], names) -> list[dict]`
  - `find_leaks(text: str, names) -> list[str]` (sorted, lower-cased matches)
  - `scan_snapshot(path, names) -> dict[str, list[str]]` (file name → matches; empty dict = clean)

- [ ] **Step 1: Write the failing tests**

`tests/test_sanitize.py`:
```python
import gzip
import json

from helpers import FLAGS, flat_span
from rootcause import sanitize

NAMES = sanitize.flag_names(FLAGS)


def test_flag_names_read_from_file():
    assert "paymentFailure" in NAMES and "recommendationCacheFailure" in NAMES


def test_spans_lose_flag_events_attributes_hidden_services_and_flagd_calls():
    spans = [
        flat_span(span_id="keep", attrs={"http.method": "POST", "feature_flag.key": "paymentFailure"},
                  events=[{"name": "feature_flag.evaluation", "attributes": {"feature_flag.result.variant": "on"}},
                          {"name": "exception", "attributes": {"exception.message": "Invalid token"}}],
                  error=True, message="Payment request failed. Invalid token."),
        flat_span(service="flagd", span_id="hidden"),
        flat_span(service="cart", span_id="calls-flagd", attrs={"url.full": "http://flagd:8013/flagd.evaluation.v2.Service/ResolveFloat"}),
    ]
    out = sanitize.sanitize_spans(spans, NAMES)
    assert [s["span_id"] for s in out] == ["keep"]
    kept = out[0]
    assert kept["attributes"] == {"http.method": "POST"}
    assert [e["name"] for e in kept["events"]] == ["exception"]
    assert kept["message"] == "Payment request failed. Invalid token."
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_logs_are_redacted_and_hidden_services_dropped():
    logs = [{"ts": "t", "service": "checkout", "severity": "INFO", "severity_number": 9,
             "body": "Warning: FeatureFlag 'kafkaQueueProblems' is activated, overloading queue now.", "trace_id": ""},
            {"ts": "t", "service": "flagd", "severity": "INFO", "severity_number": 9, "body": "reload", "trace_id": ""},
            {"ts": "t", "service": "payment", "severity": "ERROR", "severity_number": 17, "body": "Invalid token", "trace_id": "x"}]
    out = sanitize.sanitize_logs(logs, NAMES)
    assert [l["service"] for l in out] == ["checkout", "payment"]
    assert "overloading queue now" in out[0]["body"] and "[redacted]" in out[0]["body"]
    assert sanitize.find_leaks(json.dumps(out), NAMES) == []


def test_find_leaks_catches_names_and_phrases_case_insensitively():
    text = "paymentfailure then Feature Flag then feature_flag.key then FLAGD"
    assert sanitize.find_leaks(text, NAMES) == ["feature flag", "feature_flag", "flagd", "paymentfailure"]


def test_scan_snapshot_reads_plain_and_gz_files(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps({"rps": {"payment": [[1, 2]]}}))
    with gzip.open(tmp_path / "logs.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"body": "adHighCpu is on"}) + "\n")
    with gzip.open(tmp_path / "spans.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps({"name": "clean"}) + "\n")
    assert sanitize.scan_snapshot(tmp_path, NAMES) == {"logs.jsonl.gz": ["adhighcpu"]}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sanitize.py -q`
Expected: FAIL: `cannot import name 'sanitize'`

- [ ] **Step 3: Implement `rootcause/sanitize.py`**

```python
"""Remove anything that reveals the injected fault before telemetry is stored or shown to an agent."""
import gzip
import json
import re
from pathlib import Path

from rootcause import config

PHRASES = [r"feature[\s_\-]?flags?", r"flagd", r"openfeature"]
SNAPSHOT_TOOL_FILES = ("metrics.json", "spans.jsonl.gz", "logs.jsonl.gz")  # what agent tools can read


def flag_names(flags_file=config.FLAGS_FILE):
    return sorted(json.loads(Path(flags_file).read_text())["flags"])


def leak_pattern(names):
    return re.compile("|".join([re.escape(n) for n in names] + PHRASES), re.IGNORECASE)


def _redact(obj, pat):
    return json.loads(pat.sub("[redacted]", json.dumps(obj)))


def sanitize_spans(spans, names):
    pat = leak_pattern(names)
    kept = []
    for sp in spans:
        if sp["service"] in config.HIDDEN_SERVICES:
            continue
        attrs = {k: v for k, v in sp["attributes"].items() if not k.startswith("feature_flag")}
        # ponytail: drops whole spans that call the flag service; their children lose a parent, fine for diagnosis
        if any(pat.search(str(v)) for v in attrs.values()):
            continue
        events = [e for e in sp["events"] if not e["name"].startswith("feature_flag")]
        kept.append(_redact(dict(sp, attributes=attrs, events=events), pat))
    return kept


def sanitize_logs(logs, names):
    pat = leak_pattern(names)
    return [_redact(lg, pat) for lg in logs if lg["service"] not in config.HIDDEN_SERVICES]


def find_leaks(text, names):
    return sorted({m.group(0).lower() for m in leak_pattern(names).finditer(text)})


def scan_snapshot(path, names):
    path, found = Path(path), {}
    for name in SNAPSHOT_TOOL_FILES:
        p = path / name
        if not p.exists():
            continue
        if name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                text = f.read()
        else:
            text = p.read_text(encoding="utf-8")
        hits = find_leaks(text, names)
        if hits:
            found[name] = hits
    return found
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sanitize.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add rootcause/sanitize.py tests/test_sanitize.py
git commit -m "Add sanitiser and leak finder for spans, logs and snapshots

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Fault injector with guaranteed restore

**Files:**
- Create: `rootcause/inject.py`, `tests/test_inject.py`

**Interfaces:**
- Consumes: `config.FLAGS_FILE`
- Produces:
  - `flag_variants(flags_file=config.FLAGS_FILE) -> dict[str, list[str]]`
  - `class Injector(flags_file=config.FLAGS_FILE, run=<subprocess runner>)` with `apply(injection: dict)` and `restore()`. `injection` = `{"flags": {name: variant}, "docker": [{"action": "pause", "container": c} | {"action": "cpus", "container": c, "value": float}]}`

- [ ] **Step 1: Write the failing tests**

`tests/test_inject.py`:
```python
import json
import shutil

import pytest

from helpers import FLAGS
from rootcause.inject import Injector, flag_variants


@pytest.fixture
def flags_file(tmp_path):
    f = tmp_path / "demo.flagd.json"
    shutil.copy(FLAGS, f)
    return f


def test_flag_variants():
    v = flag_variants(FLAGS)
    assert "50%" in v["paymentFailure"] and "on" in v["recommendationCacheFailure"]


def test_apply_sets_default_variant_and_restore_brings_back_original(flags_file):
    original = flags_file.read_text()
    inj = Injector(flags_file=flags_file, run=lambda cmd: None)
    inj.apply({"flags": {"paymentFailure": "50%", "adHighCpu": "on"}})
    flags = json.loads(flags_file.read_text())["flags"]
    assert flags["paymentFailure"]["defaultVariant"] == "50%" and flags["adHighCpu"]["defaultVariant"] == "on"
    inj.restore()
    assert flags_file.read_text() == original
    assert not flags_file.with_name(flags_file.name + ".orig").exists()


def test_unknown_variant_is_rejected_before_any_change(flags_file):
    original = flags_file.read_text()
    with pytest.raises(ValueError):
        Injector(flags_file=flags_file, run=lambda cmd: None).apply({"flags": {"paymentFailure": "999%"}})
    assert flags_file.read_text() == original


def test_docker_actions_are_undone_in_reverse(flags_file):
    calls = []
    inj = Injector(flags_file=flags_file, run=calls.append)
    inj.apply({"docker": [{"action": "pause", "container": "valkey-cart"},
                          {"action": "cpus", "container": "currency", "value": 0.05}]})
    inj.restore()
    assert calls == [["docker", "pause", "valkey-cart"],
                     ["docker", "update", "--cpus", "0.05", "currency"],
                     ["docker", "update", "--cpus", "0", "currency"],
                     ["docker", "unpause", "valkey-cart"]]


def test_restore_runs_every_undo_even_if_one_fails(flags_file):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[1] == "update" and cmd[3] == "0":
            raise RuntimeError("update failed")

    inj = Injector(flags_file=flags_file, run=run)
    inj.apply({"flags": {"paymentFailure": "50%"},
               "docker": [{"action": "pause", "container": "valkey-cart"},
                          {"action": "cpus", "container": "currency", "value": 0.05}]})
    original = FLAGS.read_text()
    with pytest.raises(RuntimeError):
        inj.restore()
    assert ["docker", "unpause", "valkey-cart"] in calls
    assert flags_file.read_text() == original
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inject.py -q`
Expected: FAIL: `No module named 'rootcause.inject'`

- [ ] **Step 3: Implement `rootcause/inject.py`**

```python
"""Turn faults on and off: flagd flags (by editing the file flagd watches) and docker actions."""
import json
import shutil
import subprocess
from pathlib import Path

from rootcause import config


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def flag_variants(flags_file=config.FLAGS_FILE):
    flags = json.loads(Path(flags_file).read_text())["flags"]
    return {name: list(spec.get("variants", {})) for name, spec in flags.items()}


class Injector:
    def __init__(self, flags_file=config.FLAGS_FILE, run=_run):
        self.flags_file = Path(flags_file)
        self.backup = self.flags_file.with_name(self.flags_file.name + ".orig")
        self.run = run
        self._undo = []

    def apply(self, injection):
        flags = injection.get("flags") or {}
        if flags:
            cfg = json.loads(self.flags_file.read_text())
            for name, variant in flags.items():
                if variant not in cfg["flags"].get(name, {}).get("variants", {}):
                    raise ValueError(f"flag {name!r} has no variant {variant!r}")
            if not self.backup.exists():  # an existing backup is the pristine copy from an interrupted run
                shutil.copy(self.flags_file, self.backup)
            for name, variant in flags.items():
                cfg["flags"][name]["defaultVariant"] = variant
            self.flags_file.write_text(json.dumps(cfg, indent=2))
        for act in injection.get("docker") or []:
            c = act["container"]
            if act["action"] == "pause":
                self.run(["docker", "pause", c])
                self._undo.append(["docker", "unpause", c])
            elif act["action"] == "cpus":
                self.run(["docker", "update", "--cpus", str(act["value"]), c])
                self._undo.append(["docker", "update", "--cpus", "0", c])  # 0 = no CPU limit
            else:
                raise ValueError(f"unknown docker action {act['action']!r}")

    def restore(self):
        errors = []
        if self.backup.exists():
            shutil.copy(self.backup, self.flags_file)
            self.backup.unlink()
        while self._undo:
            cmd = self._undo.pop()
            try:
                self.run(cmd)
            except Exception as e:  # keep undoing the rest; report at the end
                errors.append(f"{' '.join(cmd)}: {e}")
        if errors:
            raise RuntimeError("restore incomplete: " + "; ".join(errors))
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_inject.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add rootcause/inject.py tests/test_inject.py
git commit -m "Add fault injector (flags + docker) with guaranteed restore

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Signal catalog and checks

**Files:**
- Create: `rootcause/signals.py`, `tests/test_signals.py`

**Interfaces:**
- Consumes: `config.HIDDEN_SERVICES, config.KNOWN_TARGETS`; a `prom_range`-shaped function (Task 2)
- Produces:
  - `SIGNALS: dict[str, tuple[str, str]]` (signal → (label kind `"service"|"container"`, PromQL)); signals `rps, error_ratio, p95_ms, mem_mb, cpu_cores, uptime_s`; checks may also use the derived signal `restarts`
  - `FLOORS: dict[str, float]`
  - `fetch_series(prom_range, start, end, step) -> dict[str, dict[str, list[list[float]]]]`
  - `window_stat(points, start, end, stat="mean") -> float | None`
  - `restarts(points, start, end) -> int`
  - `evaluate(checks: list[dict], metrics, baseline: tuple, fault: tuple) -> list[dict]` (each result has `target, value, baseline, passed` or `reason`)

- [ ] **Step 1: Write the failing tests**

`tests/test_signals.py`:
```python
from rootcause import signals

BASE, FAULT = (0, 100), (200, 300)


def series(before, after):
    return [[t, before] for t in range(0, 101, 20)] + [[t, after] for t in range(200, 301, 20)]


def test_window_stat_mean_max_and_empty():
    pts = [[0, 1.0], [10, 3.0], [20, 5.0]]
    assert signals.window_stat(pts, 0, 10) == 2.0
    assert signals.window_stat(pts, 0, 20, "max") == 5.0
    assert signals.window_stat(pts, 50, 60) is None


def test_restarts_counts_uptime_drops():
    pts = [[0, 100], [10, 110], [20, 5], [30, 15], [40, 2]]
    assert signals.restarts(pts, 0, 40) == 2
    assert signals.restarts(pts, 0, 10) == 0


def test_evaluate_absolute_ratio_and_star_checks():
    metrics = {"error_ratio": {"payment": series(0.0, 0.5), "cart": series(0.0, 0.0)},
               "p95_ms": {"product-catalog": series(10, 45)}}
    checks = [{"service": "payment", "signal": "error_ratio", "at_least": 0.2},
              {"service": "product-catalog", "signal": "p95_ms", "ratio_at_least": 4},
              {"service": "*", "signal": "error_ratio", "at_most": 0.1}]
    res = signals.evaluate(checks, metrics, BASE, FAULT)
    by = {(r["target"], r["signal"], "at_most" in r): r["passed"] for r in res}
    assert by[("payment", "error_ratio", False)] is True
    assert by[("product-catalog", "p95_ms", False)] is True        # 45 / 10 = 4.5
    assert by[("payment", "error_ratio", True)] is False           # 0.5 > 0.1
    assert by[("cart", "error_ratio", True)] is True


def test_ratio_uses_floor_when_baseline_is_zero():
    metrics = {"error_ratio": {"cart": series(0.0, 0.031)}}
    res = signals.evaluate([{"service": "cart", "signal": "error_ratio", "ratio_at_least": 3}], metrics, BASE, FAULT)
    assert res[0]["passed"] is True                                # 0.031 / floor 0.01 = 3.1


def test_missing_data_fails_with_reason():
    res = signals.evaluate([{"service": "email", "signal": "mem_mb", "stat": "max", "ratio_at_least": 2}], {}, BASE, FAULT)
    assert res[0]["passed"] is False and res[0]["reason"] == "no data"


def test_restarts_check_uses_uptime_series():
    metrics = {"uptime_s": {"recommendation": [[0, 100], [100, 200], [220, 5], [260, 40], [280, 3]]}}
    res = signals.evaluate([{"service": "recommendation", "signal": "restarts", "at_least": 1}], metrics, BASE, FAULT)
    assert res[0]["passed"] is True and res[0]["value"] == 2


def test_fetch_series_filters_hidden_unknown_and_nan():
    def prom_range(query, start, end, step):
        return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": [[1, "0.5"], [2, "NaN"]]},
                {"metric": {"service_name": "flagd", "container_name": "flagd"}, "values": [[1, "1"]]},
                {"metric": {"service_name": "grafana", "container_name": "grafana"}, "values": [[1, "1"]]}]
    out = signals.fetch_series(prom_range, 0, 10, 5)
    assert set(out) == set(signals.SIGNALS)
    assert out["rps"] == {"payment": [[1.0, 0.5]]}
    assert out["mem_mb"] == {"payment": [[1.0, 0.5]]}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_signals.py -q`
Expected: FAIL: `cannot import name 'signals'`

- [ ] **Step 3: Implement `rootcause/signals.py`**

```python
"""Derived per-service signals (PromQL), window statistics, and scenario signal checks."""
from rootcause import config

_CALLS = "traces_span_metrics_calls_total"
_RATE = f"sum by (service_name) (rate({_CALLS}[2m]))"
SIGNALS = {
    "rps": ("service", _RATE),
    "error_ratio": ("service", f'(sum by (service_name) (rate({_CALLS}{{status_code="STATUS_CODE_ERROR"}}[2m])) '
                               f"or 0 * {_RATE}) / {_RATE}"),
    "p95_ms": ("service", "histogram_quantile(0.95, sum by (service_name, le) "
                          "(rate(traces_span_metrics_duration_milliseconds_bucket[2m])))"),
    "mem_mb": ("container", "max by (container_name) (container_memory_usage_total_bytes) / 1e6"),
    "cpu_cores": ("container", "max by (container_name) (rate(container_cpu_usage_nanoseconds_total[2m])) / 1e9"),
    "uptime_s": ("container", "max by (container_name) (container_uptime_seconds)"),
}
# Ratios divide by max(baseline, floor) so a near-zero baseline doesn't explode the ratio.
FLOORS = {"rps": 0.1, "error_ratio": 0.01, "p95_ms": 5.0, "mem_mb": 5.0, "cpu_cores": 0.02, "restarts": 1.0}


def fetch_series(prom_range, start, end, step):
    out = {}
    for signal, (kind, query) in SIGNALS.items():
        label = "service_name" if kind == "service" else "container_name"
        out[signal] = {}
        for r in prom_range(query, start, end, step):
            name = r["metric"].get(label)
            if not name or name in config.HIDDEN_SERVICES or name not in config.KNOWN_TARGETS:
                continue
            out[signal][name] = [[float(t), float(v)] for t, v in r["values"] if v not in ("NaN", "+Inf", "-Inf")]
    return out


def window_stat(points, start, end, stat="mean"):
    vals = [v for t, v in points if start <= t <= end]
    if not vals:
        return None
    return max(vals) if stat == "max" else sum(vals) / len(vals)


def restarts(points, start, end):
    """Uptime drops inside [start, end]; the last point before start is included so a restart right at the
    window edge still counts."""
    before = [v for t, v in points if t < start][-1:]
    vals = before + [v for t, v in points if start <= t <= end]
    return sum(1 for a, b in zip(vals, vals[1:]) if b < a)


def evaluate(checks, metrics, baseline, fault):
    results = []
    for chk in checks:
        signal = chk["signal"]
        source = metrics.get("uptime_s" if signal == "restarts" else signal, {})
        targets = sorted(source) if chk["service"] == "*" else [chk["service"]]
        for target in targets:
            pts = source.get(target)
            if signal == "restarts" and pts:
                value, base = restarts(pts, *fault), restarts(pts, *baseline)
            elif pts:
                stat = chk.get("stat", "mean")
                value, base = window_stat(pts, *fault, stat), window_stat(pts, *baseline, stat)
            else:
                value = base = None
            if value is None:
                results.append({**chk, "target": target, "passed": False, "reason": "no data"})
                continue
            ok = True
            if "at_least" in chk:
                ok = ok and value >= chk["at_least"]
            if "at_most" in chk:
                ok = ok and value <= chk["at_most"]
            if "ratio_at_least" in chk:
                ok = ok and value / max(base or 0.0, FLOORS[signal]) >= chk["ratio_at_least"]
            results.append({**chk, "target": target, "value": value, "baseline": base, "passed": bool(ok)})
    return results
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_signals.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add rootcause/signals.py tests/test_signals.py
git commit -m "Add signal catalog, window stats and scenario signal checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Scenario library and validation

**Files:**
- Create: `rootcause/scenarios.py`, `tests/test_scenarios.py`, and 21 files in `scenarios/` (listed in Step 5)

**Interfaces:**
- Consumes: `config.KNOWN_TARGETS, config.SCENARIOS_DIR, config.SETTLE_S`; `signals.SIGNALS`; `inject.flag_variants` output shape
- Produces:
  - `@dataclass(frozen=True) Scenario(id, category, alert, inject: dict, truth: dict, checks: list, settle_s: int)`; `truth = {"causes": [{"accept": [service, ...], "fault_type": "errors"|"latency"|"resource"}]}` (controls: `causes: []`)
  - `CATEGORIES`, `FAULT_TYPES`
  - `load_all(directory=config.SCENARIOS_DIR) -> list[Scenario]` (id = file stem, sorted)
  - `validate(scenario, variants: dict[str, list[str]]) -> list[str]` (empty = valid)

- [ ] **Step 1: Write the failing tests**

`tests/test_scenarios.py`:
```python
from helpers import FLAGS
from rootcause import scenarios
from rootcause.inject import flag_variants

VARIANTS = flag_variants(FLAGS)


def make(**over):
    base = dict(id="x", category="easy", alert="Some orders fail at checkout.",
                inject={"flags": {"paymentFailure": "50%"}},
                truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]},
                checks=[{"service": "payment", "signal": "error_ratio", "at_least": 0.2}], settle_s=180)
    base.update(over)
    return scenarios.Scenario(**base)


def test_all_shipped_scenarios_are_valid_and_unique():
    loaded = scenarios.load_all()
    assert len(loaded) >= 20
    assert len({s.id for s in loaded}) == len(loaded)
    problems = {s.id: scenarios.validate(s, VARIANTS) for s in loaded}
    assert {k: v for k, v in problems.items() if v} == {}
    assert sum(s.category == "control" for s in loaded) >= 4


def test_valid_example_passes():
    assert scenarios.validate(make(), VARIANTS) == []


def test_alert_must_not_name_the_root_cause_or_a_flag():
    errs = scenarios.validate(make(alert="The payment service is failing"), VARIANTS)
    assert any("names root cause payment" in e for e in errs)
    errs = scenarios.validate(make(alert="paymentFailure happened"), VARIANTS)
    assert any("mentions flag" in e for e in errs)


def test_bad_flag_variant_category_signal_and_target_are_reported():
    errs = scenarios.validate(make(category="weird", inject={"flags": {"paymentFailure": "7%"}},
                                   checks=[{"service": "nope", "signal": "vibes", "at_least": 1}]), VARIANTS)
    joined = " | ".join(errs)
    for needle in ("unknown category", "no variant 7%", "unknown signal vibes", "unknown check target nope"):
        assert needle in joined


def test_controls_have_no_causes_and_incidents_need_checks():
    assert any("controls" in e for e in scenarios.validate(make(category="control"), VARIANTS))
    assert any("no signal checks" in e for e in scenarios.validate(make(checks=[]), VARIANTS))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scenarios.py -q`
Expected: FAIL: `cannot import name 'scenarios'`

- [ ] **Step 3: Implement `rootcause/scenarios.py`**

```python
"""Scenario library: YAML definitions of injected incidents, their ground truth and signal checks."""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from rootcause import config, signals

CATEGORIES = {"easy", "hard-cross-service", "hard-silent", "hard-noisy", "hard-two-faults", "control"}
FAULT_TYPES = {"errors", "latency", "resource"}
DOCKER_ACTIONS = {"pause", "cpus"}


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str
    alert: str
    inject: dict
    truth: dict
    checks: list
    settle_s: int = config.SETTLE_S


def load_all(directory=config.SCENARIOS_DIR):
    out = []
    for path in sorted(Path(directory).glob("*.yaml")):
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        out.append(Scenario(id=path.stem, category=d["category"], alert=d["alert"], inject=d.get("inject") or {},
                            truth=d["truth"], checks=d.get("checks") or [], settle_s=d.get("settle_s", config.SETTLE_S)))
    return out


def validate(s, variants):
    errs = []
    if s.category not in CATEGORIES:
        errs.append(f"unknown category {s.category}")
    if not s.alert.strip():
        errs.append("empty alert")
    for name in variants:
        if name.lower() in s.alert.lower():
            errs.append(f"alert mentions flag {name}")
    for flag, variant in (s.inject.get("flags") or {}).items():
        if flag not in variants:
            errs.append(f"unknown flag {flag}")
        elif variant not in variants[flag]:
            errs.append(f"flag {flag} has no variant {variant}")
    for act in s.inject.get("docker") or []:
        if act.get("action") not in DOCKER_ACTIONS:
            errs.append(f"unknown docker action {act.get('action')}")
        if act.get("container") not in config.KNOWN_TARGETS:
            errs.append(f"unknown container {act.get('container')}")
    causes = s.truth.get("causes")
    if causes is None:
        errs.append("truth.causes missing")
        causes = []
    for cause in causes:
        if not cause.get("accept"):
            errs.append("cause without accept list")
        if cause.get("fault_type") not in FAULT_TYPES:
            errs.append(f"unknown fault_type {cause.get('fault_type')}")
        for svc in cause.get("accept", []):
            if svc not in config.KNOWN_TARGETS:
                errs.append(f"unknown truth service {svc}")
            if re.search(rf"\b{re.escape(svc)}\b", s.alert, re.IGNORECASE):
                errs.append(f"alert names root cause {svc}")
    if (s.category == "control") != (causes == []):
        errs.append("controls (and only controls) must have no causes")
    if s.category != "control" and not s.checks:
        errs.append("no signal checks")
    for chk in s.checks:
        if chk.get("signal") not in signals.SIGNALS and chk.get("signal") != "restarts":
            errs.append(f"unknown signal {chk.get('signal')}")
        if chk.get("service") != "*" and chk.get("service") not in config.KNOWN_TARGETS:
            errs.append(f"unknown check target {chk.get('service')}")
        if not any(k in chk for k in ("at_least", "at_most", "ratio_at_least")):
            errs.append(f"check without a threshold: {chk}")
    return errs
```

- [ ] **Step 4: Run the unit tests (the library test still fails: no YAML yet)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scenarios.py -q`
Expected: `1 failed, 4 passed` (`test_all_shipped_scenarios_are_valid_and_unique`)

- [ ] **Step 5: Write the 21 scenario files**

`scenarios/payment-failure-50.yaml`
```yaml
category: easy
alert: "Customers report that some orders are failing at checkout."
inject: {flags: {paymentFailure: "50%"}}
truth: {causes: [{accept: [payment], fault_type: errors}]}
checks:
  - {service: payment, signal: error_ratio, at_least: 0.2}
```

`scenarios/cart-failure-50.yaml`
```yaml
category: easy
alert: "Some customers see errors when their basket is cleared after placing an order."
inject: {flags: {cartFailure: "50%"}}
truth: {causes: [{accept: [cart], fault_type: errors}]}
checks:
  - {service: cart, signal: error_ratio, at_least: 0.02}
```

`scenarios/ad-failure.yaml`
```yaml
category: easy
alert: "Sponsored banners intermittently fail to show on the storefront."
inject: {flags: {adFailure: "on"}}
truth: {causes: [{accept: [ad], fault_type: errors}]}
checks:
  - {service: ad, signal: error_ratio, at_least: 0.03}
```

`scenarios/product-catalog-failure.yaml`
```yaml
category: easy
alert: "Opening one particular product shows an error page."
inject: {flags: {productCatalogFailure: "on"}}
truth: {causes: [{accept: [product-catalog], fault_type: errors}]}
checks:
  - {service: product-catalog, signal: error_ratio, at_least: 0.01}
```

`scenarios/payment-unreachable.yaml`
```yaml
category: hard-cross-service
alert: "Every checkout attempt is failing right now."
inject: {flags: {paymentUnreachable: "on"}}
truth: {causes: [{accept: [payment], fault_type: errors}]}
checks:
  - {service: checkout, signal: error_ratio, at_least: 0.1}
```

`scenarios/kafka-queue-problems.yaml`
```yaml
category: hard-cross-service
alert: "Order processing downstream of purchases is falling behind."
inject: {flags: {kafkaQueueProblems: "on"}}
truth: {causes: [{accept: [kafka, checkout, fraud-detection], fault_type: latency}]}
checks:
  - {service: fraud-detection, signal: p95_ms, ratio_at_least: 2}
```

`scenarios/valkey-cart-paused.yaml`
```yaml
category: hard-cross-service
alert: "Adding items to the basket fails."
inject: {docker: [{action: pause, container: valkey-cart}]}
truth: {causes: [{accept: [valkey-cart], fault_type: errors}]}
checks:
  - {service: cart, signal: error_ratio, at_least: 0.1}
```

`scenarios/recommendation-cache-leak.yaml`
```yaml
category: hard-silent
alert: "Users say product pages have become slow over the last few minutes."
inject: {flags: {recommendationCacheFailure: "on"}}
truth: {causes: [{accept: [recommendation], fault_type: resource}]}
checks:
  - {service: recommendation, signal: mem_mb, stat: max, ratio_at_least: 2}
```

`scenarios/email-memory-leak.yaml`
```yaml
category: hard-silent
alert: "Customers say order confirmation messages arrive late or not at all."
inject: {flags: {emailMemoryLeak: "1000x"}}
truth: {causes: [{accept: [email], fault_type: resource}]}
checks:
  - {service: email, signal: mem_mb, stat: max, ratio_at_least: 1.5}
```

`scenarios/product-catalog-lock-contention.yaml`
```yaml
category: hard-silent
alert: "Browsing the storefront has become sluggish."
inject: {flags: {productCatalogLockContention: "on"}}
truth: {causes: [{accept: [product-catalog], fault_type: latency}]}
checks:
  - {service: product-catalog, signal: p95_ms, ratio_at_least: 2}
```

`scenarios/ad-high-cpu.yaml`
```yaml
category: hard-silent
alert: "The storefront feels slower than usual on some pages."
inject: {flags: {adHighCpu: "on"}}
truth: {causes: [{accept: [ad], fault_type: resource}]}
checks:
  - {service: ad, signal: cpu_cores, ratio_at_least: 2}
```

`scenarios/currency-cpu-throttle.yaml`
```yaml
category: hard-silent
alert: "Product pages and checkout have become slow."
inject: {docker: [{action: cpus, container: currency, value: 0.05}]}
truth: {causes: [{accept: [currency], fault_type: latency}]}
checks:
  - {service: currency, signal: p95_ms, ratio_at_least: 3}
```

`scenarios/image-slow-load.yaml`
```yaml
category: hard-silent
alert: "Product pictures load very slowly."
inject: {flags: {imageSlowLoad: "5sec"}}
truth: {causes: [{accept: [frontend-proxy, image-provider], fault_type: latency}]}
checks:
  - {service: frontend-proxy, signal: p95_ms, ratio_at_least: 1.5}
```

`scenarios/payment-failure-with-flood.yaml`
```yaml
category: hard-noisy
alert: "Some orders are failing while the site is under unusually heavy traffic."
inject: {flags: {paymentFailure: "50%", loadGeneratorFloodHomepage: "on"}}
truth: {causes: [{accept: [payment], fault_type: errors}]}
checks:
  - {service: payment, signal: error_ratio, at_least: 0.2}
  - {service: frontend, signal: rps, ratio_at_least: 1.5}
```

`scenarios/lock-contention-with-flood.yaml`
```yaml
category: hard-noisy
alert: "The site has become slow during a traffic surge."
inject: {flags: {productCatalogLockContention: "on", loadGeneratorFloodHomepage: "on"}}
truth: {causes: [{accept: [product-catalog], fault_type: latency}]}
checks:
  - {service: product-catalog, signal: p95_ms, ratio_at_least: 2}
  - {service: frontend, signal: rps, ratio_at_least: 1.5}
```

`scenarios/payment-failure-and-recommendation-leak.yaml`
```yaml
category: hard-two-faults
alert: "Some orders fail, and the whole site is getting slower."
inject: {flags: {paymentFailure: "50%", recommendationCacheFailure: "on"}}
truth:
  causes:
    - {accept: [payment], fault_type: errors}
    - {accept: [recommendation], fault_type: resource}
checks:
  - {service: payment, signal: error_ratio, at_least: 0.2}
  - {service: recommendation, signal: mem_mb, stat: max, ratio_at_least: 2}
```

`scenarios/cart-failure-and-ad-high-cpu.yaml`
```yaml
category: hard-two-faults
alert: "Some customers see basket errors and pages feel slow."
inject: {flags: {cartFailure: "50%", adHighCpu: "on"}}
truth:
  causes:
    - {accept: [cart], fault_type: errors}
    - {accept: [ad], fault_type: resource}
checks:
  - {service: cart, signal: error_ratio, at_least: 0.02}
  - {service: ad, signal: cpu_cores, ratio_at_least: 2}
```

`scenarios/control-1.yaml`
```yaml
category: control
alert: "A customer says the site felt slow earlier today."
truth: {causes: []}
checks:
  - {service: "*", signal: error_ratio, at_most: 0.15}
```

`scenarios/control-2.yaml`
```yaml
category: control
alert: "Someone reported seeing an error once at checkout."
truth: {causes: []}
checks:
  - {service: "*", signal: error_ratio, at_most: 0.15}
```

`scenarios/control-3.yaml`
```yaml
category: control
alert: "A user complains that product images looked blurry."
truth: {causes: []}
checks:
  - {service: "*", signal: error_ratio, at_most: 0.15}
```

`scenarios/control-4.yaml`
```yaml
category: control
alert: "Support asks whether anything is wrong with the shop right now."
truth: {causes: []}
checks:
  - {service: "*", signal: error_ratio, at_most: 0.15}
```

- [ ] **Step 6: Run all scenario tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scenarios.py -q`
Expected: `5 passed`. If validation reports a problem in a YAML file, fix the file (not the rule) and rerun.

- [ ] **Step 7: Commit**

```bash
git add rootcause/scenarios.py tests/test_scenarios.py scenarios
git commit -m "Add scenario library (17 incidents + 4 controls) with validation rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Snapshot capture and loading

**Files:**
- Create: `rootcause/snapshot.py`, `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `backends.flatten_otlp, backends.flatten_log`; `sanitize.sanitize_spans, sanitize.sanitize_logs, sanitize.scan_snapshot`; `signals.fetch_series, signals.evaluate`; a `fetch` object with `prom_range, jaeger_raw, os_logs` (the `backends` module or a fake)
- Produces:
  - `capture(scenario, t_inject: float, t_end: float, names, fetch=backends, out_dir=config.SNAPSHOTS, demo_commit="") -> dict` with keys `scenario, path, valid, results, leaks`
  - Snapshot dir files: `meta.json` (`scenario_id, category, alert, baseline_start, fault_start, end, demo_commit`), `truth.json`, `metrics.json`, `spans.jsonl.gz`, `logs.jsonl.gz`, `validation.json` (`valid, results, leaks`)
  - `load(path) -> dict` with keys `meta, metrics, spans, logs` (never truth)
  - `load_truth(path) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_snapshot.py`:
```python
import json
from pathlib import Path
from types import SimpleNamespace

from helpers import FLAGS, otlp_payload
from rootcause import sanitize, snapshot
from rootcause.scenarios import Scenario

NAMES = sanitize.flag_names(FLAGS)
T_INJECT, T_END = 100_000.0, 100_180.0
SCENARIO = Scenario(id="payment-test", category="easy", alert="Some orders fail at checkout.",
                    inject={"flags": {"paymentFailure": "50%"}},
                    truth={"causes": [{"accept": ["payment"], "fault_type": "errors"}]},
                    checks=[{"service": "payment", "signal": "error_ratio", "at_least": 0.2}])


def fake_fetch(prom_value_after=0.5, t_inject=T_INJECT):
    """Every series is 0 before t_inject and prom_value_after from then on."""
    def prom_range(query, start, end, step):
        vals = [[t, str(prom_value_after) if t >= t_inject else "0"] for t in range(int(start), int(end) + 1, step)]
        return [{"metric": {"service_name": "payment", "container_name": "payment"}, "values": vals}]

    def jaeger_raw(service, start, end, limit):
        if service != "payment":
            return {"result": {"resourceSpans": []}}
        return otlp_payload("payment", [
            {"span_id": "a", "name": "charge", "error": True, "message": "Invalid token",
             "events": [("feature_flag.evaluation", {"feature_flag.key": "paymentFailure"})]},
            {"span_id": "b", "name": "flag lookup", "attrs": {"url.full": "http://flagd:8013/x"}},
        ])

    def os_logs(query, start, end, size):
        if '"payment"' not in query:
            return []
        return [{"@timestamp": "t", "resource": {"service.name": "payment"},
                 "severity": {"text": "ERROR", "number": 17}, "body": "Payment request failed. Invalid token."},
                {"@timestamp": "t", "resource": {"service.name": "payment"},
                 "severity": {"text": "INFO", "number": 9}, "body": "FeatureFlag 'paymentFailure' is activated"}]

    return SimpleNamespace(prom_range=prom_range, jaeger_raw=jaeger_raw, os_logs=os_logs)


def test_capture_writes_sanitised_valid_snapshot(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(), out_dir=tmp_path, demo_commit="abc")
    path = Path(out["path"])
    assert out["valid"] is True and out["leaks"] == {}
    for name in ("meta.json", "truth.json", "metrics.json", "spans.jsonl.gz", "logs.jsonl.gz", "validation.json"):
        assert (path / name).exists(), name
    snap = snapshot.load(path)
    assert snap["meta"]["fault_start"] == T_INJECT and snap["meta"]["demo_commit"] == "abc"
    assert "truth" not in snap
    assert [s["span_id"] for s in snap["spans"]] == ["a"]
    assert snap["spans"][0]["events"] == []
    assert any("[redacted]" in l["body"] for l in snap["logs"])
    assert snapshot.load_truth(path) == SCENARIO.truth
    assert json.loads((path / "validation.json").read_text())["valid"] is True


def test_capture_marks_invalid_when_signal_is_too_weak(tmp_path):
    out = snapshot.capture(SCENARIO, T_INJECT, T_END, NAMES, fetch=fake_fetch(prom_value_after=0.05), out_dir=tmp_path)
    assert out["valid"] is False
    assert out["results"][0]["passed"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot.py -q`
Expected: FAIL: `cannot import name 'snapshot'`

- [ ] **Step 3: Implement `rootcause/snapshot.py`**

```python
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
    path = Path(out_dir) / f"{scenario.id}__{stamp}"
    path.mkdir(parents=True)
    meta = {"scenario_id": scenario.id, "category": scenario.category, "alert": scenario.alert,
            "baseline_start": baseline_start, "fault_start": t_inject, "end": t_end, "demo_commit": demo_commit}
    (path / "meta.json").write_text(json.dumps(meta, indent=1))
    (path / "truth.json").write_text(json.dumps(scenario.truth, indent=1))
    (path / "metrics.json").write_text(json.dumps(metrics))
    _write_jsonl_gz(path / "spans.jsonl.gz", spans)
    _write_jsonl_gz(path / "logs.jsonl.gz", logs)

    results = signals.evaluate(scenario.checks, metrics, (baseline_start, t_inject), (t_inject + config.RAMP_S, t_end))
    leaks = sanitize.scan_snapshot(path, names)
    valid = all(r["passed"] for r in results) and not leaks
    (path / "validation.json").write_text(json.dumps({"valid": valid, "results": results, "leaks": leaks}, indent=1))
    return {"scenario": scenario.id, "path": str(path), "valid": valid, "results": results, "leaks": leaks}


def load(path):
    path = Path(path)
    return {"meta": json.loads((path / "meta.json").read_text()),
            "metrics": json.loads((path / "metrics.json").read_text()),
            "spans": _read_jsonl_gz(path / "spans.jsonl.gz"),
            "logs": _read_jsonl_gz(path / "logs.jsonl.gz")}


def load_truth(path):
    return json.loads((Path(path) / "truth.json").read_text())
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_snapshot.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add rootcause/snapshot.py tests/test_snapshot.py
git commit -m "Add snapshot capture (sanitised, validated, leak-scanned) and loaders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Harness: cool-down, record one, record all

**Files:**
- Create: `rootcause/harness.py`, `tests/test_harness.py`

**Interfaces:**
- Consumes: `snapshot.capture`; an injector with `apply(dict)` / `restore()` (Task 4); `config.STATE_FILE, config.COOLDOWN_S, config.SNAPSHOTS`
- Produces:
  - `wait_cooldown(now=time.time, sleep=time.sleep, state_file=config.STATE_FILE) -> float` (seconds waited)
  - `mark_restored(t: float, state_file=config.STATE_FILE)`
  - `record(scenario, names, injector, fetch=backends, now=time.time, sleep=time.sleep, state_file=config.STATE_FILE, out_dir=config.SNAPSHOTS, demo_commit="") -> dict` (the `capture` summary)
  - `record_all(scenarios, names, injector, **kwargs) -> list[dict]`; appends one JSON line per scenario to `out_dir/index.jsonl`

- [ ] **Step 1: Write the failing tests**

`tests/test_harness.py`:
```python
import json

import pytest

from helpers import FLAGS, Clock
from rootcause import harness, sanitize, config
from rootcause.scenarios import Scenario
from test_snapshot import SCENARIO, fake_fetch

NAMES = sanitize.flag_names(FLAGS)


class FakeInjector:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def apply(self, injection):
        self.calls.append("apply")
        if self.fail_on and self.fail_on in json.dumps(injection):
            raise RuntimeError("inject failed")

    def restore(self):
        self.calls.append("restore")


def run(tmp_path, clock, injector, scenario=SCENARIO, fetch=None):
    return harness.record(scenario, NAMES, injector, fetch=fetch or fake_fetch(t_inject=clock.t), now=clock.now,
                          sleep=clock.sleep, state_file=tmp_path / "state.json", out_dir=tmp_path / "snaps")


def failing_prom_range(*args):
    raise RuntimeError("prometheus down")


def test_record_injects_waits_captures_and_restores(tmp_path):
    clock, inj = Clock(), FakeInjector()
    out = run(tmp_path, clock, inj)
    assert inj.calls == ["apply", "restore"]
    assert clock.sleeps == [SCENARIO.settle_s]
    assert out["valid"] is True
    assert json.loads((tmp_path / "state.json").read_text())["last_restore"] == clock.t


def test_restore_happens_even_when_capture_fails(tmp_path):
    clock, inj = Clock(), FakeInjector()
    broken = fake_fetch()
    broken.prom_range = failing_prom_range
    with pytest.raises(RuntimeError, match="prometheus down"):
        run(tmp_path, clock, inj, fetch=broken)
    assert inj.calls == ["apply", "restore"]
    assert (tmp_path / "state.json").exists()


def test_cooldown_waits_for_the_remaining_time(tmp_path):
    clock = Clock()
    harness.mark_restored(clock.t - 60, tmp_path / "state.json")
    waited = harness.wait_cooldown(clock.now, clock.sleep, tmp_path / "state.json")
    assert waited == config.COOLDOWN_S - 60 and clock.sleeps == [config.COOLDOWN_S - 60]


def test_record_all_continues_after_a_failure_and_writes_index(tmp_path):
    clock = Clock()
    bad = Scenario(id="bad", category="easy", alert="x", inject={"flags": {"adFailure": "on"}},
                   truth=SCENARIO.truth, checks=SCENARIO.checks)
    summaries = harness.record_all([bad, SCENARIO], NAMES, FakeInjector(fail_on="adFailure"), fetch=fake_fetch(t_inject=clock.t),
                                   now=clock.now, sleep=clock.sleep, state_file=tmp_path / "state.json",
                                   out_dir=tmp_path / "snaps")
    assert [s["scenario"] for s in summaries] == ["bad", "payment-test"]
    assert "inject failed" in summaries[0]["error"]
    lines = (tmp_path / "snaps" / "index.jsonl").read_text().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_harness.py -q`
Expected: FAIL: `cannot import name 'harness'`

- [ ] **Step 3: Implement `rootcause/harness.py`**

```python
"""Record incidents: wait for a clean baseline, inject, capture a snapshot, always restore."""
import json
import time
from pathlib import Path

from rootcause import backends, config, snapshot


def mark_restored(t, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_restore": t}))


def wait_cooldown(now=time.time, sleep=time.sleep, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    if not state_file.exists():
        return 0.0
    remaining = config.COOLDOWN_S - (now() - json.loads(state_file.read_text())["last_restore"])
    if remaining <= 0:
        return 0.0
    print(f"  cooling down {remaining / 60:.1f} min so the baseline window is fault-free", flush=True)
    sleep(remaining)
    return remaining


def record(scenario, names, injector, fetch=backends, now=time.time, sleep=time.sleep,
           state_file=config.STATE_FILE, out_dir=config.SNAPSHOTS, demo_commit=""):
    wait_cooldown(now, sleep, state_file)
    t_inject = now()
    try:
        injector.apply(scenario.inject)
        sleep(scenario.settle_s)
        return snapshot.capture(scenario, t_inject, now(), names, fetch, out_dir, demo_commit)
    finally:
        injector.restore()
        mark_restored(now(), state_file)


def record_all(scenarios, names, injector, out_dir=config.SNAPSHOTS, **kwargs):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for i, sc in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {sc.id} ({sc.category})", flush=True)
        try:
            summary = record(sc, names, injector, out_dir=out_dir, **kwargs)
        except Exception as e:  # one broken scenario must not stop the batch
            summary = {"scenario": sc.id, "valid": False, "error": f"{type(e).__name__}: {e}"}
        summaries.append(summary)
        with open(out_dir / "index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in summary.items() if k != "results"}) + "\n")
        print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
    return summaries
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_harness.py -q`
Expected: `4 passed`

- [ ] **Step 5: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all tests pass (`34 passed`)

- [ ] **Step 6: Commit**

```bash
git add rootcause/harness.py tests/test_harness.py
git commit -m "Add harness: cool-down gate, record with guaranteed restore, batch recording

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Environment wrapper, CLI, and first live recording

**Files:**
- Create: `rootcause/env.py`, `rootcause/cli.py`, `rootcause/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above
- Produces: `env.compose(*args)`, `env.demo_commit() -> str`, `env.probe() -> dict`; `cli.build_parser()`, `cli.main(argv=None) -> int`; `python -m rootcause {up,down,status,list,reset-flags,record [ids…|--all],leak-check [paths…]}`

- [ ] **Step 1: Write the failing CLI test**

`tests/test_cli.py`:
```python
from rootcause import cli


def test_parser_accepts_all_commands():
    p = cli.build_parser()
    assert p.parse_args(["record", "payment-failure-50", "control-1"]).ids == ["payment-failure-50", "control-1"]
    assert p.parse_args(["record", "--all"]).all is True
    assert p.parse_args(["leak-check"]).paths == []
    for cmd in ("up", "down", "status", "list", "reset-flags"):
        assert p.parse_args([cmd]).cmd == cmd


def test_list_prints_scenarios(capsys):
    assert cli.main(["list"]) == 0
    assert "payment-failure-50" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli.py -q`
Expected: FAIL: `cannot import name 'cli'`

- [ ] **Step 3: Implement `rootcause/env.py`**

```python
"""Docker Compose wrapper for the vendored OpenTelemetry Demo, plus a quick stack probe."""
import subprocess
import time

from rootcause import backends, config, signals


def compose(*args):
    files = [x for f in config.COMPOSE_FILES for x in ("-f", f)]
    subprocess.run(["docker", "compose", *files, *args], cwd=config.DEMO, check=True)


def demo_commit():
    try:
        return subprocess.run(["git", "-C", str(config.DEMO), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def probe():
    now = time.time()
    return {"services_with_traffic": len(backends.prom_range(signals.SIGNALS["rps"][1], now - 300, now, 60)),
            "jaeger_services": len(backends.jaeger_services()),
            "recent_log_records": len(backends.os_logs("*", now - 300, now, 5))}
```

- [ ] **Step 4: Implement `rootcause/cli.py` and `rootcause/__main__.py`**

`rootcause/cli.py`:
```python
"""Command line: manage the demo, list/record scenarios, check snapshots for leaks."""
import argparse
import json
from pathlib import Path

from rootcause import config, env, harness, inject, sanitize, scenarios


def build_parser():
    p = argparse.ArgumentParser(prog="rootcause")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("up", "down", "status", "list", "reset-flags"):
        sub.add_parser(name)
    rec = sub.add_parser("record", help="inject scenarios and capture snapshots")
    rec.add_argument("ids", nargs="*")
    rec.add_argument("--all", action="store_true")
    leak = sub.add_parser("leak-check", help="scan snapshots for anything revealing the fault")
    leak.add_argument("paths", nargs="*")
    return p


def _record(args):
    chosen = scenarios.load_all()
    if not args.all:
        unknown = set(args.ids) - {s.id for s in chosen}
        if unknown or not args.ids:
            print(f"unknown or missing scenario ids: {sorted(unknown)}")
            return 2
        chosen = [s for s in chosen if s.id in args.ids]
    variants = inject.flag_variants()
    problems = {s.id: scenarios.validate(s, variants) for s in chosen}
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        print(json.dumps(problems, indent=1))
        return 2
    summaries = harness.record_all(chosen, sanitize.flag_names(), inject.Injector(), demo_commit=env.demo_commit())
    return 0 if all(s["valid"] for s in summaries) else 1


def _leak_check(args):
    paths = [Path(p) for p in args.paths] or sorted(p for p in config.SNAPSHOTS.glob("*__*") if p.is_dir())
    names = sanitize.flag_names()
    found = {str(p): sanitize.scan_snapshot(p, names) for p in paths}
    found = {k: v for k, v in found.items() if v}
    print(f"scanned {len(paths)} snapshots; leaks: {json.dumps(found, indent=1) if found else 'none'}")
    return 1 if found else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "up":
        env.compose("up", "-d", "--quiet-pull")
    elif args.cmd == "down":
        env.compose("down")
    elif args.cmd == "status":
        print(json.dumps(env.probe(), indent=1))
    elif args.cmd == "list":
        for s in scenarios.load_all():
            print(f"{s.id:45s} {s.category}")
    elif args.cmd == "reset-flags":
        inject.Injector().restore()
        print("flags restored")
    elif args.cmd == "record":
        return _record(args)
    elif args.cmd == "leak-check":
        return _leak_check(args)
    return 0
```

`rootcause/__main__.py`:
```python
import sys

from rootcause.cli import main

sys.exit(main())
```

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (`36 passed`)

- [ ] **Step 6: Commit**

```bash
git add rootcause/env.py rootcause/cli.py rootcause/__main__.py tests/test_cli.py
git commit -m "Add demo wrapper and CLI (up/down/status/list/reset-flags/record/leak-check)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Live: start the demo and probe it**

Run: `.venv/Scripts/python.exe -m rootcause up && .venv/Scripts/python.exe -c "import time; time.sleep(180)" && .venv/Scripts/python.exe -m rootcause status`
Expected: `services_with_traffic` ≥ 15, `jaeger_services` ≥ 15, `recent_log_records` = 5.

- [ ] **Step 8: Live: verify the docker CPU-limit undo works**

Run:
```bash
docker update --cpus 0.5 currency && docker inspect currency --format '{{.HostConfig.NanoCpus}}' \
 && docker update --cpus 0 currency && docker inspect currency --format '{{.HostConfig.NanoCpus}}'
```
Expected: `500000000` then `0`. If the second command fails or doesn't print `0`, delete `scenarios/currency-cpu-throttle.yaml` and note it in `scenarios/NOTES.md` (Task 10).

- [ ] **Step 9: Live: record one easy scenario end to end**

Run: `.venv/Scripts/python.exe -m rootcause record payment-failure-50`
Expected (about 4 minutes, no cool-down on the first run): `-> valid=True`. Then:
```bash
.venv/Scripts/python.exe -m rootcause leak-check
git -C vendor/opentelemetry-demo status --short src/flagd/demo.flagd.json
```
Expected: `leaks: none`, and no output from git status (the flag file is restored).

- [ ] **Step 10: Inspect the snapshot by eye**

Run:
```bash
.venv/Scripts/python.exe - <<'EOF'
import glob, json
from rootcause import snapshot
p = sorted(glob.glob("data/snapshots/payment-failure-50__*"))[-1]
s = snapshot.load(p)
print(p, json.dumps(json.load(open(p + "/validation.json"))["results"], indent=1))
print("spans:", len(s["spans"]), "error spans:", sum(x["error"] for x in s["spans"]), "logs:", len(s["logs"]))
print("payment error_ratio tail:", s["metrics"]["error_ratio"]["payment"][-4:])
print("sample error span:", next(x for x in s["spans"] if x["error"])["message"][:120])
EOF
```
Expected: payment `error_ratio` ≈ 0.3–0.6 in the tail, several error spans whose messages mention the failed charge, several hundred logs, and nothing mentioning flags. Record what you see in the task report. If anything is wrong, fix it (with a test) before Task 10.

---

### Task 10: Record the full library and review it

**Files:**
- Create: `scenarios/NOTES.md`
- Modify (only if justified by evidence): individual `scenarios/*.yaml`

**Interfaces:**
- Consumes: the CLI from Task 9
- Produces: `data/snapshots/*` for every scenario plus `data/snapshots/index.jsonl`; `scenarios/NOTES.md` documenting each scenario's outcome

- [ ] **Step 1: Record everything in the background (~8 hours; 18-min cool-down each)**

Run (background, from `D:\rootcause`): `.venv/Scripts/python.exe -m rootcause record --all > data/record_all.log 2>&1`
Keep the laptop awake and plugged in. Progress: `tail -f data/record_all.log`.

- [ ] **Step 2: Summarise results**

Run:
```bash
.venv/Scripts/python.exe - <<'EOF'
import json
rows = [json.loads(l) for l in open("data/snapshots/index.jsonl")]
latest = {r["scenario"]: r for r in rows}
for sid, r in sorted(latest.items()):
    print(f"{sid:45s} valid={r['valid']} {r.get('error', '')}")
print(sum(r["valid"] for r in latest.values()), "of", len(latest), "valid")
EOF
.venv/Scripts/python.exe -m rootcause leak-check
```
Expected: `leaks: none`. Some scenarios may be invalid; that is information, not failure.

- [ ] **Step 3: Review every invalid scenario against its evidence**

For each invalid scenario, open its `validation.json` and look at the relevant series in `metrics.json`. Decide one of:
- **Weak but real** (the signal moved clearly, just under the threshold): switch to a stronger variant (e.g. `cartFailure` 50% → 100%) and re-record with `python -m rootcause record <id>`. Do not lower a threshold below a level where the change is plainly visible in the series.
- **Not visible** (the series shows no change): delete the scenario file.
- **Harness problem** (error in `index.jsonl`): fix it with a test, then re-record.

- [ ] **Step 4: Write `scenarios/NOTES.md`**

One row per scenario, with the observed values from `validation.json`:
```markdown
# Scenario validation notes (recorded 2026-09-XX, demo commit cbaf761)

| Scenario | Category | Valid | Observed signal | Decision |
|---|---|---|---|---|
| payment-failure-50 | easy | yes | payment error_ratio 0.46 (baseline 0.00) | keep |
```

- [ ] **Step 5: Final checks and commit**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m rootcause leak-check && git -C vendor/opentelemetry-demo status --short`
Expected: all tests pass, `leaks: none`, no modified vendor files.

```bash
git add scenarios
git commit -m "Record and validate the scenario library; document outcomes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Week 1 is done when:** ≥ 16 valid incidents (including all 4 controls) are recorded, the leak check is clean on every snapshot, all tests pass, and NOTES.md explains every scenario that was changed or dropped.

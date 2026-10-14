"""Builders shared by tests: OTLP payloads, flat spans and logs, metric series, snapshots, run records, fakes."""
import json
from pathlib import Path
from types import SimpleNamespace

from rootcause import snapshot
from rootcause.scenarios import Scenario

FLAGS = Path(__file__).parent / "fixtures" / "demo.flagd.json"


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


def flat_log(service, body, ts="t"):
    return {"ts": ts, "service": service, "severity": "INFO", "severity_number": 9, "body": body, "trace_id": ""}


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


# --- metric series and snapshots in memory ---

META = {"baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}


def series(base, fault):
    # baseline covers t=0..900 (the sample at fault_start is pre-fault traffic); fault starts at 915
    return [[float(t), base] for t in range(0, 901, 15)] + [[float(t), fault] for t in range(915, 1215, 15)]


def snap(metrics):
    return {"meta": META, "metrics": metrics, "spans": [], "logs": []}


# --- a recordable scenario and fake telemetry backends ---

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


# --- a fake docker runner ---

INFO = ["docker", "info", "--format", "{{.NCPU}}"]


def fake_run(calls, fail=None, ncpu="16\n"):
    """Runner fake: records commands, answers `docker info` with ncpu, optionally fails some commands."""
    def run(cmd):
        calls.append(cmd)
        if cmd == INFO:
            return ncpu
        if fail:
            fail(cmd)
        return ""
    return run


# --- files on disk, in the layouts the code writes ---

def write_snapshot(d, metrics=None, spans=(), logs=(), truth=None):
    """A snapshot directory as snapshot.capture lays it out (without validation.json)."""
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"alert": "x", "baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}))
    (d / "metrics.json").write_text(json.dumps(metrics or {}))
    snapshot._write_jsonl_gz(d / "spans.jsonl.gz", list(spans))
    snapshot._write_jsonl_gz(d / "logs.jsonl.gz", list(logs))
    (d / "truth.json").write_text(json.dumps(truth or {"causes": []}))
    return d


def write_record(d, sid, cat, run, correct, **extra):
    """A run record as evaluate.run lays it out. Score fields other than `correct` follow from it;
    `extra` adds top-level fields or replaces them (`score=...` included)."""
    d.mkdir(parents=True, exist_ok=True)
    score = {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None if cat == "control" else correct == 1.0,
             "false_alarm": cat == "control" and correct == 0.0, "abstained": False}
    (d / f"{sid}__{run}.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": run, "score": score, **extra}))

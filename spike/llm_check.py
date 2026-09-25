"""Check 3: can a free Gemini model use telemetry tools to find an injected fault's root cause?

Usage: python llm_check.py <flag> <variant> "<vague alert text>"
Injects the fault, waits, runs one tool-calling investigation with Gemini (free tier),
prints each model's tool calls and final answer, then restores the flags.
"""
import json
import os
import sys
import time
from collections import Counter

from dotenv import load_dotenv
from openai import APITimeoutError, InternalServerError, OpenAI, RateLimitError

from common import ROOT, jaeger_services, jaeger_traces, logs, prom, reset_flags, set_flag, wait

load_dotenv(ROOT / ".env")
GEMINI = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=os.getenv("GEMINI_API_KEY"), timeout=90)
# (label, [primary, fallbacks...]) -- free-tier models get overloaded (503), so each run has a fallback chain
RUNS = [("flash", ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]),
        ("flash-lite", ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"])]


# ---------------------------------------------------------------- tools (compact outputs)
def service_health(window="3m", baseline_offset="15m"):
    """Per-service RED metrics + container memory/CPU, each compared with the same window `baseline_offset` ago."""
    def get(q):
        return {r["metric"].get("service_name") or r["metric"].get("container_name"): float(r["value"][1])
                for r in prom(q) if r["value"][1] not in ("NaN", "+Inf")}
    calls = "rate(traces_span_metrics_calls_total{sel}[{w}]{off})"
    def red(off):
        o = f" offset {off}" if off else ""
        rate = get("sum by (service_name) (" + calls.format(sel="", w=window, off=o) + ")")
        err = get("sum by (service_name) (" + calls.format(sel='{status_code="STATUS_CODE_ERROR"}', w=window, off=o) + ")")
        p95 = get(f"histogram_quantile(0.95, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket[{window}]{o})))")
        mem = get(f"max by (container_name) (container_memory_usage_total_bytes{o})")
        cpu = get(f"max by (container_name) (container_cpu_utilization_ratio{o})")
        return rate, err, p95, mem, cpu
    now, before = red(None), red(baseline_offset)
    lines = []
    for s_ in sorted(set(now[0]) | set(now[3])):
        rate, err, p95, mem, cpu = (d.get(s_) for d in now)
        brate, berr, bp95, bmem, bcpu = (d.get(s_) for d in before)
        parts = [s_]
        if rate:
            parts.append(f"err {(err or 0) / rate:.3f}<-{((berr or 0) / brate if brate else 0):.3f}")
            parts.append(f"p95 {p95 or 0:.0f}<-{bp95 or 0:.0f}ms")
        if mem:
            parts.append(f"mem {mem / 1e6:.0f}<-{(bmem or 0) / 1e6:.0f}MB")
        if cpu is not None:
            parts.append(f"cpu {cpu:.2f}<-{bcpu or 0:.2f}")
        lines.append(" | ".join(parts))
    return {"format": f"service | metric now<-{baseline_offset} earlier (window {window})", "services": lines}


def top_changes(window="3m", baseline_offset="15m", n=8):
    """Every (service, signal) ranked by how much it moved vs the baseline window."""
    def get(q):
        return {r["metric"].get("service_name") or r["metric"].get("container_name"): float(r["value"][1])
                for r in prom(q) if r["value"][1] not in ("NaN", "+Inf")}
    sig = {
        "error_ratio": ('sum by (service_name) (rate(traces_span_metrics_calls_total{{status_code="STATUS_CODE_ERROR"}}[{w}]{o})) '
                        '/ sum by (service_name) (rate(traces_span_metrics_calls_total[{w}]{o}))'),
        "p95_ms": "histogram_quantile(0.95, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket[{w}]{o})))",
        "memory_MB": "max by (container_name) (container_memory_usage_total_bytes{o}) / 1e6",
        "cpu": "max by (container_name) (container_cpu_utilization_ratio{o})",
    }
    floor = {"error_ratio": 0.01, "p95_ms": 5, "memory_MB": 5, "cpu": 0.05}  # ignore changes on tiny values
    rows = []
    for name, q in sig.items():
        now, before = get(q.format(w=window, o="")), get(q.format(w=window, o=f" offset {baseline_offset}"))
        for svc, v in now.items():
            b = before.get(svc, 0.0)
            score = abs(v - b) / max(abs(b), floor[name])
            rows.append((score, f"{svc} {name}: {b:.3g} -> {v:.3g} ({'+' if v >= b else ''}{(v - b) / max(abs(b), floor[name]) * 100:.0f}%)"))
    return {"biggest_changes_vs_" + baseline_offset + "_earlier": [r for _, r in sorted(rows, reverse=True)[:n]]}


def query_metrics(promql):
    res = prom(promql)[:15]
    return [{"labels": r["metric"], "value": r["value"][1]} for r in res]


def search_traces(service, errors_only=True, limit=20):
    known = jaeger_services()
    if service not in known:
        return {"error": f"unknown service {service!r}", "valid_services": known}
    spans = jaeger_traces(service, lookback_min=5, limit=limit, errors_only=errors_only)
    ops = Counter(f"{sp['service']}:{sp['name']}" for sp in spans if sp["error"])
    msgs = Counter(f"{sp['service']}: {sp['message'][:120]}" for sp in spans if sp["error"] and sp["message"])
    slow = sorted(spans, key=lambda sp: -sp["ms"])[:5]
    return {"spans_found": len(spans), "error_spans_by_service_op": dict(ops.most_common(8)),
            "error_messages": dict(msgs.most_common(5)),
            "slowest_spans_ms": [(round(sp["ms"]), f"{sp['service']}:{sp['name']}") for sp in slow]}


def search_logs(service, text="", minutes=5):
    q = f'resource.service.name:"{service}"' + (f" AND ({text})" if text else "")
    hits = logs(q, minutes=minutes, size=8)
    return {"total": hits["total"]["value"],
            "samples": [{"severity": (h["_source"].get("severity") or {}).get("text"), "body": str(h["_source"].get("body"))[:160]}
                        for h in hits["hits"]]}


TOOLS = {"top_changes": top_changes, "service_health": service_health, "query_metrics": query_metrics,
         "search_traces": search_traces, "search_logs": search_logs}
SCHEMAS = [
    {"type": "function", "function": {"name": "top_changes", "description": "Start here. Ranks every service's error ratio, p95 latency, memory and CPU by how much it changed vs 15 minutes ago.",
                                      "parameters": {"type": "object", "properties": {"n": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "service_health", "description": "Overview of every service: error ratio, p95 latency, container memory and CPU, each with its value from 15 minutes earlier so you can see what changed.",
                                      "parameters": {"type": "object", "properties": {"window": {"type": "string", "description": "e.g. 3m"}}}}},
    {"type": "function", "function": {"name": "query_metrics", "description": "Run a PromQL query. Span metrics: traces_span_metrics_calls_total{service_name,span_name,status_code}, traces_span_metrics_duration_milliseconds_bucket. Container metrics may also exist.",
                                      "parameters": {"type": "object", "properties": {"promql": {"type": "string"}}, "required": ["promql"]}}},
    {"type": "function", "function": {"name": "search_traces", "description": "Summarise recent traces for a service: error spans by service/operation, error messages, slowest spans.",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "errors_only": {"type": "boolean"}, "limit": {"type": "integer"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "search_logs", "description": "Recent log records for a service, optional Lucene filter text (e.g. severity.number:>=17 for errors).",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "text": {"type": "string"}, "minutes": {"type": "integer"}}, "required": ["service"]}}},
]
SYSTEM = ("You are an SRE investigating a production incident in a microservice shop. Use the tools to gather evidence; "
          "follow errors/latency downstream until you reach the service where the problem originates. "
          "The alert describes a user-visible symptom; the service it mentions is often NOT the cause. "
          "Prefer signals that changed recently over values that were always high. "
          'Finish with ONLY a JSON object: {"root_cause_service": str, "fault_type": "errors|latency|resource|other", '
          '"evidence": [str], "confidence": 0-1}.')


def chat(models, **kw):
    """Call the first model that answers; retry each once on overload/rate limit before falling back."""
    last = None
    for model in models:
        for attempt in range(3):
            try:
                return model, GEMINI.chat.completions.create(model=model, **kw)
            except (InternalServerError, RateLimitError, APITimeoutError) as e:
                last = e
                time.sleep(10 * 2 ** attempt)
    raise last


def investigate(label, models, alert, max_steps=15):
    print(f"\n### {label}")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"ALERT: {alert}"}]
    t0, calls, used = time.time(), 0, set()
    for _ in range(max_steps):
        model, r = chat(models, messages=msgs, tools=SCHEMAS, temperature=0)
        used.add(model)
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            print(f"  models used: {sorted(used)}")
            print(f"  answer ({calls} tool calls, {time.time() - t0:.0f}s): {(m.content or '').strip()[:700]}")
            return m.content
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            try:
                out = TOOLS[tc.function.name](**args)
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            calls += 1
            print(f"  -> {tc.function.name}({json.dumps(args)[:90]})")
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)[:6000]})
            TRANSCRIPT.append({"model_label": label, "tool": tc.function.name, "args": args, "output": out})
    print("  gave up: step limit reached")
    return None


TRANSCRIPT = []

if __name__ == "__main__":
    flag, variant, alert = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        set_flag(flag, variant)
        wait(180, f"{flag}={variant} active")
        for label, models in RUNS:
            try:
                investigate(label, models, alert)
            except Exception as e:
                print(f"  {label} failed: {type(e).__name__}: {str(e)[:300]}")
    finally:
        reset_flags()
        out_dir = ROOT / "runs"
        out_dir.mkdir(exist_ok=True)
        f = out_dir / f"spike_{flag}_{int(time.time())}.json"
        f.write_text(json.dumps(TRANSCRIPT, indent=1, default=str))
        print(f"\nflags restored; transcript -> {f}")

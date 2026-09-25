"""Check 3: can a free LLM use telemetry tools to find an injected fault's root cause?

Usage: python llm_check.py <flag> <variant> "<vague alert text>"
Injects the fault, waits, runs one tool-calling investigation per provider (Gemini, Groq),
prints each model's tool calls and final answer, then restores the flags.
"""
import json
import os
import sys
import time
from collections import Counter

from dotenv import load_dotenv
from openai import OpenAI

from common import ROOT, jaeger_traces, logs, prom, reset_flags, set_flag, wait

load_dotenv(ROOT / ".env")
PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", ["flash"]),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", ["gpt-oss-120b", "llama-3.3-70b", "qwen3-32b"]),
}


# ---------------------------------------------------------------- tools (compact outputs)
def service_health(window="5m"):
    q_rate = f"sum by (service_name) (rate(traces_span_metrics_calls_total[{window}]))"
    q_err = f'sum by (service_name) (rate(traces_span_metrics_calls_total{{status_code="STATUS_CODE_ERROR"}}[{window}]))'
    q_p95 = f"histogram_quantile(0.95, sum by (service_name, le) (rate(traces_span_metrics_duration_milliseconds_bucket[{window}])))"
    get = lambda q: {r["metric"].get("service_name"): float(r["value"][1]) for r in prom(q) if r["value"][1] != "NaN"}
    rate, err, p95 = get(q_rate), get(q_err), get(q_p95)
    rows = [{"service": s, "req_per_s": round(rate[s], 2), "error_ratio": round(err.get(s, 0) / rate[s], 3) if rate[s] else 0,
             "p95_ms": round(p95.get(s, 0))} for s in sorted(rate)]
    return rows


def query_metrics(promql):
    res = prom(promql)[:15]
    return [{"labels": r["metric"], "value": r["value"][1]} for r in res]


def search_traces(service, errors_only=True, limit=20):
    traces = jaeger_traces(service, lookback="5m", limit=limit, tags={"error": "true"} if errors_only else None)
    ops, msgs, slow = Counter(), Counter(), []
    for t in traces:
        procs = {k: v["serviceName"] for k, v in t["processes"].items()}
        for sp in t["spans"]:
            tags = {tg["key"]: tg["value"] for tg in sp.get("tags", [])}
            if tags.get("error") in (True, "true") or tags.get("otel.status_code") == "ERROR":
                ops[f'{procs[sp["processID"]]}:{sp["operationName"]}'] += 1
                m = tags.get("otel.status_description") or tags.get("exception.message") or tags.get("rpc.grpc.status_code")
                if m:
                    msgs[f'{procs[sp["processID"]]}: {str(m)[:120]}'] += 1
            slow.append((sp["duration"] / 1000, f'{procs[sp["processID"]]}:{sp["operationName"]}'))
    slow = sorted(slow, reverse=True)[:5]
    return {"traces_found": len(traces), "error_spans_by_service_op": dict(ops.most_common(8)),
            "error_messages": dict(msgs.most_common(5)), "slowest_spans_ms": [(round(d), n) for d, n in slow]}


def search_logs(service, text="", minutes=5):
    q = f'resource.service.name:"{service}"' + (f" AND ({text})" if text else "")
    hits = logs(q, minutes=minutes, size=8)
    return {"total": hits["total"]["value"],
            "samples": [{"severity": h["_source"].get("severityText"), "body": str(h["_source"].get("body"))[:160]}
                        for h in hits["hits"]]}


TOOLS = {"service_health": service_health, "query_metrics": query_metrics,
         "search_traces": search_traces, "search_logs": search_logs}
SCHEMAS = [
    {"type": "function", "function": {"name": "service_health", "description": "Per-service request rate, error ratio and p95 latency over a window.",
                                      "parameters": {"type": "object", "properties": {"window": {"type": "string", "description": "e.g. 5m"}}}}},
    {"type": "function", "function": {"name": "query_metrics", "description": "Run a PromQL query. Span metrics: traces_span_metrics_calls_total{service_name,span_name,status_code}, traces_span_metrics_duration_milliseconds_bucket. Container metrics may also exist.",
                                      "parameters": {"type": "object", "properties": {"promql": {"type": "string"}}, "required": ["promql"]}}},
    {"type": "function", "function": {"name": "search_traces", "description": "Summarise recent traces for a service: error spans by service/operation, error messages, slowest spans.",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "errors_only": {"type": "boolean"}, "limit": {"type": "integer"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "search_logs", "description": "Recent log records for a service, optional Lucene filter text (e.g. severityText:ERROR).",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}, "text": {"type": "string"}, "minutes": {"type": "integer"}}, "required": ["service"]}}},
]
SYSTEM = ("You are an SRE investigating a production incident in a microservice shop. Use the tools to gather evidence; "
          "follow errors/latency downstream until you reach the service where the problem originates. "
          'Finish with ONLY a JSON object: {"root_cause_service": str, "fault_type": "errors|latency|resource|other", '
          '"evidence": [str], "confidence": 0-1}.')


def pick_model(client, prefs):
    ids = sorted(m.id for m in client.models.list())
    for p in prefs:
        cands = [i for i in ids if p in i and "lite" not in i and "tts" not in i and "image" not in i and "audio" not in i]
        if cands:
            return sorted(cands)[-1]
    raise RuntimeError(f"no preferred model among {ids[:30]}")


def investigate(name, alert, max_steps=10):
    base, env, prefs = PROVIDERS[name]
    if not os.getenv(env):
        print(f"\n### {name}: skipped ({env} not set in .env)")
        return None
    client = OpenAI(base_url=base, api_key=os.getenv(env))
    model = pick_model(client, prefs)
    print(f"\n### {name}: {model}")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"ALERT: {alert}"}]
    t0, calls = time.time(), 0
    for _ in range(max_steps):
        r = client.chat.completions.create(model=model, messages=msgs, tools=SCHEMAS, temperature=0)
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            print(f"  answer ({calls} tool calls, {time.time() - t0:.0f}s): {m.content.strip()[:600]}")
            return m.content
        for tc in m.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            try:
                out = TOOLS[tc.function.name](**args)
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"}
            calls += 1
            print(f"  -> {tc.function.name}({json.dumps(args)[:90]})")
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(out)[:3500]})
    print("  gave up: step limit reached")
    return None


if __name__ == "__main__":
    flag, variant, alert = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        set_flag(flag, variant)
        wait(150, f"{flag}={variant} active")
        for provider in PROVIDERS:
            try:
                investigate(provider, alert)
            except Exception as e:
                print(f"  {provider} failed: {type(e).__name__}: {str(e)[:300]}")
    finally:
        reset_flags()
        print("\nflags restored")

"""Check 2: does each kind of injected fault leave a clear, findable signal?

For three faults of different kinds (errors, latency, memory leak) this measures the relevant
signal before and during the fault, then always restores the flags.
"""
import sys

from common import jaeger_traces, logs, prom, reset_flags, set_flag, wait

ERR_RATE = ('sum by (service_name) (rate(traces_span_metrics_calls_total{{status_code="STATUS_CODE_ERROR"}}[{w}])) '
            '/ sum by (service_name) (rate(traces_span_metrics_calls_total[{w}]))')
P95 = ('histogram_quantile(0.95, sum by (service_name, le) '
       '(rate(traces_span_metrics_duration_milliseconds_bucket[{w}])))')


def by_service(result):
    return {r["metric"].get("service_name", "?"): float(r["value"][1]) for r in result if r["value"][1] != "NaN"}


def top(d, n=4):
    return ", ".join(f"{k}={v:.3g}" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n])


def snapshot(label, w="3m"):
    err, p95 = by_service(prom(ERR_RATE.format(w=w))), by_service(prom(P95.format(w=w)))
    print(f"  [{label}] highest error rates: {top(err)}")
    print(f"  [{label}] highest p95 latency ms: {top(p95)}")
    return err, p95


def memory(container):
    res = prom(f'max(container_memory_usage_total_bytes{{container_name="{container}"}})')
    return float(res[0]["value"][1]) / 1e6 if res else None


FAULTS = {
    "paymentFailure": ("100%", "errors", "payment"),
    "intlShippingSlowdown": ("5sec", "latency", "shipping"),
    "recommendationCacheFailure": ("on", "memory leak", "recommendation"),
}

try:
    for flag, (variant, kind, service) in FAULTS.items():
        if len(sys.argv) > 1 and flag not in sys.argv[1:]:
            continue
        print(f"\n=== {flag}={variant} ({kind}, expected culprit: {service})")
        mem0 = memory(service)
        base_err, base_p95 = snapshot("before")
        set_flag(flag, variant)
        wait(180, "fault active")
        err, p95 = snapshot("during")
        mem1 = memory(service)
        err_spans = jaeger_traces(service, lookback_min=3, limit=50, errors_only=True)
        err_logs = logs(f'resource.service.name:"{service}" AND severity.number:>=17', minutes=3)
        msgs = sorted({f"{s['service']}:{s['name']}: {s['message'][:70]}" for s in err_spans})[:3]
        print(f"  Jaeger error spans in {service} traces (3m, 50 traces): {len(err_spans)}  e.g. {msgs}")
        print(f"  OpenSearch ERROR logs for {service} (3m): {err_logs['total']['value']}")
        if mem0 is not None and mem1 is not None:
            print(f"  {service} memory: {mem0:.0f} MB -> {mem1:.0f} MB")
        print(f"  signal: error rate {base_err.get(service, 0):.3f} -> {err.get(service, 0):.3f}, "
              f"p95 {base_p95.get(service, 0):.0f} -> {p95.get(service, 0):.0f} ms")
        reset_flags()
        wait(90, "recovering")
finally:
    reset_flags()
    print("\nflags restored")

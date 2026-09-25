"""Check 1: can a script reach all three telemetry backends and see live data?"""
from common import jaeger_services, jaeger_traces, logs, prom

ok = True


def check(name, fn):
    global ok
    try:
        detail = fn()
        print(f"PASS  {name}: {detail}")
    except Exception as e:  # report every backend, don't stop at the first failure
        ok = False
        print(f"FAIL  {name}: {type(e).__name__}: {e}")


check("Prometheus span metrics", lambda: f"{len(prom('sum by (service_name) (rate(traces_span_metrics_calls_total[2m]))'))} services with traffic")
check("Jaeger services", lambda: sorted(jaeger_services()))
check("Jaeger traces (checkout)", lambda: f"{len(jaeger_traces('checkout', limit=20))} traces in last 5m")
check("OpenSearch logs", lambda: f"{logs('*', size=1)['total']['value']} log records in last 5m")
print("\nALL BACKENDS REACHABLE" if ok else "\nSOME CHECKS FAILED")

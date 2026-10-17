"""Docker Compose wrapper for the vendored OpenTelemetry Demo, plus a quick stack probe."""
import subprocess
import time

from rootcause import backends, config, evaluate, signals


def compose(*args):
    files = [x for f in config.COMPOSE_FILES for x in ("-f", f)]
    subprocess.run(["docker", "compose", *files, *args], cwd=config.DEMO, check=True)


def demo_commit():
    """The vendored demo's short sha, with -dirty if its tracked files differ from it; "" without git."""
    v = evaluate.code_version(config.DEMO)
    return "" if v == "unknown" else v


def probe():
    now = time.time()
    series = backends.prom_range(signals.SIGNALS["rps"][1], now - 300, now, 60)
    return {"services_with_traffic": len({s["metric"].get("service_name") for s in series} & set(config.KNOWN_TARGETS)),
            "jaeger_services": len(backends.jaeger_services()),
            "logs_flowing": bool(backends.os_logs("*", now - 300, now, 1))}

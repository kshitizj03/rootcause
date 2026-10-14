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

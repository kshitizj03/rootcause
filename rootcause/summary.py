"""Per-service change table over a snapshot: every signal's baseline window vs its fault window, ranked."""
from rootcause import config, signals

FAULT_TYPE_OF = {"error_ratio": "errors", "p95_ms": "latency", "mem_mb": "resource", "cpu_cores": "resource",
                 "restarts": "resource", "rps": None}
STAT = {"mem_mb": "max"}  # leaks show as a peak or sawtooth; every other signal uses the mean


def windows(meta):
    return (meta["baseline_start"], meta["fault_start"]), (meta["fault_start"] + config.RAMP_S, meta["end"])


def _row(service, signal, baseline, value):
    score = abs(value - baseline) / max(abs(baseline), signals.FLOORS[signal])
    return {"service": service, "signal": signal, "baseline": baseline, "value": value, "score": score,
            "direction": "up" if value >= baseline else "down", "fault_type": FAULT_TYPE_OF[signal]}


def changes(snap):
    base_w, fault_w = windows(snap["meta"])
    rows = []
    for signal, by_service in snap["metrics"].items():
        for service, pts in by_service.items():
            if signal == "uptime_s":
                value, base = signals.restarts(pts, *fault_w), signals.restarts(pts, *base_w)
                signal_name, base = "restarts", base if base is not None else (0 if value is not None else None)
            elif signal in FAULT_TYPE_OF:
                stat = STAT.get(signal, "mean")
                value, base = signals.window_stat(pts, *fault_w, stat), signals.window_stat(pts, *base_w, stat)
                signal_name = signal
            else:
                continue
            if value is None or base is None:
                continue
            rows.append(_row(service, signal_name, base, value))
    return sorted(rows, key=lambda r: (-r["score"], r["service"], r["signal"]))

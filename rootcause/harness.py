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

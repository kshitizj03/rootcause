"""Record incidents: wait for a clean baseline, inject, capture a snapshot, always restore."""
import json
import time
from pathlib import Path

from rootcause import backends, config, snapshot


class RestoreError(RuntimeError):
    """Raised when restore fails. Carries the capture summary path if available."""
    def __init__(self, message, summary=None):
        super().__init__(message)
        self.summary = summary


def mark_restored(t, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_restore": t}), encoding="utf-8")


def wait_cooldown(now=time.time, sleep=time.sleep, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    if not state_file.exists():
        # Unknown history: wait full cooldown to be safe
        print(f"  cooling down {config.COOLDOWN_S / 60:.1f} min so the baseline window is fault-free", flush=True)
        sleep(config.COOLDOWN_S)
        return config.COOLDOWN_S
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Corrupt state: wait full cooldown to be safe
        print(f"  cooling down {config.COOLDOWN_S / 60:.1f} min so the baseline window is fault-free", flush=True)
        sleep(config.COOLDOWN_S)
        return config.COOLDOWN_S
    if "dirty" in state:
        raise RuntimeError(f"State is dirty (restore failed): {state.get('error', 'unknown error')}. Run `reset` to recover.")
    remaining = config.COOLDOWN_S - (now() - state.get("last_restore", now()))
    if remaining <= 0:
        return 0.0
    print(f"  cooling down {remaining / 60:.1f} min so the baseline window is fault-free", flush=True)
    sleep(remaining)
    return remaining


def record(scenario, names, injector, fetch=backends, now=time.time, sleep=time.sleep,
           state_file=config.STATE_FILE, out_dir=config.SNAPSHOTS, demo_commit=""):
    wait_cooldown(now, sleep, state_file)
    t_inject = now()
    summary = None
    apply_error = None
    try:
        injector.apply(scenario.inject)
        sleep(scenario.settle_s)
        t_end = now()
        sleep(config.INGEST_LAG_S)
        summary = snapshot.capture(scenario, t_inject, t_end, names, fetch, out_dir, demo_commit)
        return summary
    except Exception as e:
        apply_error = e
        raise
    finally:
        try:
            injector.restore()
        except Exception as restore_error:
            # Restore failed: write dirty state and raise RestoreError
            state_file = Path(state_file)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            error_msg = f"{type(restore_error).__name__}: {restore_error}"
            state_file.write_text(json.dumps({"dirty": True, "t": now(), "error": error_msg}), encoding="utf-8")
            # Build message: restore error + original in-flight error if there was one
            msg = error_msg
            if apply_error:
                msg = f"{msg}; prior error: {type(apply_error).__name__}: {apply_error}"
            raise RestoreError(msg, summary=summary) from restore_error
        mark_restored(now(), state_file)


def record_all(scenarios, names, injector, out_dir=config.SNAPSHOTS, **kwargs):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    consecutive_failures = 0
    for i, sc in enumerate(scenarios, 1):
        print(f"[{i}/{len(scenarios)}] {sc.id} ({sc.category})", flush=True)
        summary = None
        try:
            summary = record(sc, names, injector, out_dir=out_dir, **kwargs)
            consecutive_failures = 0
        except RestoreError as e:
            # Restore failure: write row and stop batch
            summary = {"scenario": sc.id, "valid": False, "error": str(e)}
            if e.summary:
                summary["path"] = e.summary["path"]
            summaries.append(summary)
            with open(out_dir / "index.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({k: v for k, v in summary.items() if k != "results"}) + "\n")
            print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
            raise
        except Exception as e:
            # Other failures: write row and continue; count consecutive
            consecutive_failures += 1
            summary = {"scenario": sc.id, "valid": False, "error": f"{type(e).__name__}: {e}"}
            summaries.append(summary)
            with open(out_dir / "index.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({k: v for k, v in summary.items() if k != "results"}) + "\n")
            print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
            if consecutive_failures >= 3:
                raise RuntimeError(f"Aborting after 3 consecutive failures: {e}")
            continue
        # Success path
        summaries.append(summary)
        with open(out_dir / "index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in summary.items() if k != "results"}) + "\n")
        print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
    return summaries

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


class DirtyStateError(RuntimeError):
    """Raised when state file indicates a prior restore failed."""
    pass


def mark_restored(t, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_restore": t}), encoding="utf-8")


def wait_cooldown(now=time.time, sleep=time.sleep, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    remaining = config.COOLDOWN_S  # Default: unknown history = wait full cooldown

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            # Check if state is dirty (truthy "dirty" field)
            if state.get("dirty"):
                raise DirtyStateError(f"State is dirty (restore failed): {state.get('error', 'unknown error')}. Run `reset` to recover.")
            # Calculate remaining cooldown
            remaining = config.COOLDOWN_S - (now() - state.get("last_restore", now()))
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError, UnicodeDecodeError):
            # Any unreadable state: treat as unknown history
            remaining = config.COOLDOWN_S

    # Sleep only if remaining > 0
    if remaining > 0:
        print(f"  cooling down {remaining / 60:.1f} min so the baseline window is fault-free", flush=True)
        sleep(remaining)
        return remaining
    return 0.0


def record(scenario, names, injector, fetch=backends, now=time.time, sleep=time.sleep,
           state_file=config.STATE_FILE, out_dir=config.SNAPSHOTS, demo_commit=""):
    wait_cooldown(now, sleep, state_file)
    t_inject = now()
    summary = None
    in_flight = None
    try:
        injector.apply(scenario.inject)
        sleep(scenario.settle_s)
        t_end = now()
        sleep(config.INGEST_LAG_S)
        # Assertion: t_end is before the INGEST_LAG_S sleep (captured before ingest lag)
        assert t_end <= now() - config.INGEST_LAG_S or config.INGEST_LAG_S == 0, "t_end must be captured before ingest lag sleep"
        summary = snapshot.capture(scenario, t_inject, t_end, names, fetch, out_dir, demo_commit)
        return summary
    except Exception as e:
        in_flight = e
        raise
    finally:
        try:
            injector.restore()
        except Exception as restore_error:
            # Restore failed: write dirty state and raise RestoreError
            state_file = Path(state_file)
            state_file.parent.mkdir(parents=True, exist_ok=True)
            error_msg = f"{type(restore_error).__name__}: {restore_error}"
            try:
                state_file.write_text(json.dumps({"dirty": True, "t": now(), "error": error_msg}), encoding="utf-8")
            except Exception:
                # State file write failed: don't let that mask the RestoreError
                pass
            # Build message: restore error + original in-flight error if there was one
            msg = error_msg
            if in_flight:
                msg = f"{msg}; prior error: {type(in_flight).__name__}: {in_flight}"
            raise RestoreError(msg, summary=summary) from restore_error
        mark_restored(now(), state_file)


def _write_index_row(out_dir, summary):
    """Write summary to index.jsonl (append mode)."""
    with open(out_dir / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in summary.items() if k != "results"}) + "\n")


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
        except DirtyStateError:
            # Dirty state: stop batch immediately without writing a scenario row
            raise
        except RestoreError as e:
            # Restore failure: write row and stop batch
            summary = {"scenario": sc.id, "valid": False, "error": str(e)}
            if e.summary:
                summary["path"] = e.summary["path"]
            summaries.append(summary)
            _write_index_row(out_dir, summary)
            print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
            raise
        except Exception as e:
            # Other failures: increment counter, create summary, write row
            consecutive_failures += 1
            summary = {"scenario": sc.id, "valid": False, "error": f"{type(e).__name__}: {e}"}
            summaries.append(summary)
            _write_index_row(out_dir, summary)
            print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
            if consecutive_failures >= 3:
                raise RuntimeError(f"Aborting after 3 consecutive failures: {e}")
            continue
        # Success path
        summaries.append(summary)
        _write_index_row(out_dir, summary)
        print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
    return summaries

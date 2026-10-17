"""Record incidents: wait for a clean baseline, inject, capture a snapshot, always restore."""
import json
import time
from pathlib import Path

from rootcause import backends, config, snapshot

MAX_CONSECUTIVE_FAILURES = 3  # a batch stops after this many scenarios fail in a row


class RestoreError(RuntimeError):
    """Raised when restore fails. Carries the capture summary dict (or None) so the caller can still index the snapshot."""
    def __init__(self, message, summary=None):
        super().__init__(message)
        self.summary = summary


class DirtyStateError(RuntimeError):
    """Raised when the state file is dirty: a restore failed, or a recording was killed before its restore ran."""


def mark_restored(t, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_restore": t}), encoding="utf-8")


def _write_dirty(state_file, error, t):
    state_file = Path(state_file)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"dirty": True, "t": t, "error": error}), encoding="utf-8")


def wait_cooldown(now=time.time, sleep=time.sleep, state_file=config.STATE_FILE):
    state_file = Path(state_file)
    t_now = now()
    remaining = config.COOLDOWN_S

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("dirty"):
                raise DirtyStateError(f"State is dirty (a restore failed or a recording was interrupted): "
                                      f"{state.get('error', 'unknown error')}")  # the CLI adds the reset-flags hint
            remaining = config.COOLDOWN_S - (t_now - state.get("last_restore", t_now))
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError, UnicodeDecodeError):
            remaining = config.COOLDOWN_S

    if remaining > 0:
        print(f"  cooling down {remaining / 60:.1f} min so the baseline window is fault-free", flush=True)
        sleep(remaining)
        return remaining
    return 0.0


def record(scenario, names, injector, fetch=backends, now=time.time, sleep=time.sleep,
           state_file=config.STATE_FILE, out_dir=config.SNAPSHOTS, demo_commit=""):
    wait_cooldown(now, sleep, state_file)
    # In-flight marker: only a successful restore's mark_restored clears it, so a hard kill leaves the state dirty.
    _write_dirty(state_file, f"in flight: {scenario.id}", now())
    summary = None
    in_flight = None
    try:
        injector.apply(scenario.inject)
        # Taken after apply and t_end computed, so meta timing doesn't encode how long apply took (control vs fault).
        t_inject = now()
        t_end = t_inject + scenario.settle_s
        sleep(scenario.settle_s)
        sleep(config.INGEST_LAG_S)
        summary = snapshot.capture(scenario, t_inject, t_end, names, fetch, out_dir, demo_commit)
        return summary
    except Exception as e:
        in_flight = e
        raise
    finally:
        try:
            injector.restore()
        except Exception as restore_error:
            error_msg = f"{type(restore_error).__name__}: {restore_error}"
            try:
                _write_dirty(state_file, error_msg, now())
            except Exception as write_error:
                error_msg = f"{error_msg}; state file NOT written: {type(write_error).__name__}: {write_error}"
            msg = error_msg
            if in_flight:
                msg = f"{msg}; prior error: {type(in_flight).__name__}: {in_flight}"
            raise RestoreError(msg, summary=summary) from restore_error
        mark_restored(now(), state_file)


def write_index_row(out_dir, summary):
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
        stop = None
        try:
            summary = record(sc, names, injector, out_dir=out_dir, **kwargs)
            consecutive_failures = 0
        except DirtyStateError:
            raise
        except RestoreError as e:
            summary = {"scenario": sc.id, "valid": False, "error": str(e)}
            if e.summary:
                summary["path"] = e.summary["path"]
            stop = e
        except Exception as e:
            consecutive_failures += 1
            summary = {"scenario": sc.id, "valid": False, "error": f"{type(e).__name__}: {e}"}
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                stop = RuntimeError(f"Aborting after {MAX_CONSECUTIVE_FAILURES} consecutive failures: {e}")
        summaries.append(summary)
        write_index_row(out_dir, summary)
        print(f"    -> valid={summary['valid']} {summary.get('error', '')}", flush=True)
        if stop:
            raise stop
    return summaries

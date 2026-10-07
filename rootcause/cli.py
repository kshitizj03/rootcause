"""Command line: manage the demo, list/record scenarios, check snapshots for leaks."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from rootcause import config, env, harness, inject, sanitize, scenarios, snapshot


def build_parser():
    p = argparse.ArgumentParser(prog="rootcause")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("up", "down", "status", "list", "reset-flags"):
        sub.add_parser(name)
    rec = sub.add_parser("record", help="inject scenarios and capture snapshots")
    rec.add_argument("ids", nargs="*")
    rec.add_argument("--all", action="store_true")
    leak = sub.add_parser("leak-check", help="scan snapshots for anything revealing the fault")
    leak.add_argument("paths", nargs="*")
    reval = sub.add_parser("revalidate", help="re-score recorded snapshots against the current scenario checks")
    reval.add_argument("ids", nargs="*")
    resan = sub.add_parser("resanitize", help="re-apply the current sanitisers to recorded snapshots, then revalidate")
    resan.add_argument("ids", nargs="*")
    return p


def reset_stack(injector=None, run=inject._run):
    """Undo every possible fault (flag file, docker pause/cpu limits), then mark the state clean."""
    injector = injector or inject.Injector(run=run)
    errors = []
    try:
        injector.restore()
    except Exception as e:
        errors.append(str(e))
    undo = sorted({(a["action"], a["container"])
                   for s in scenarios.load_all() for a in s.inject.get("docker") or []})
    ncpu = None
    if any(action == "cpus" for action, _ in undo):
        try:
            ncpu = inject.host_cpus(run)
        except (ValueError, subprocess.CalledProcessError, OSError) as e:
            errors.append(f"NCPU: {e}")
    for action, container in undo:
        if action == "cpus" and ncpu is None:
            continue
        cmd = (["docker", "update", "--cpus", ncpu, container] if action == "cpus"
               else ["docker", "unpause", container])
        try:
            run(cmd)
        except (subprocess.CalledProcessError, OSError) as e:
            stderr = str(getattr(e, "stderr", "") or "")
            if action == "pause" and "is not paused" in stderr.lower():
                continue
            errors.append(f"{' '.join(cmd)}: {e} {stderr}".strip())
    if errors:
        raise RuntimeError("reset incomplete: " + "; ".join(errors))
    harness.mark_restored(time.time(), config.STATE_FILE)


def _is_dirty():
    try:
        return bool(json.loads(Path(config.STATE_FILE).read_text(encoding="utf-8")).get("dirty"))
    except (OSError, ValueError, AttributeError):
        return False


def _record(args):
    chosen = scenarios.load_all()
    if not args.all:
        unknown = set(args.ids) - {s.id for s in chosen}
        if unknown or not args.ids:
            print(f"unknown or missing scenario ids: {sorted(unknown)}")
            return 2
        chosen = [s for s in chosen if s.id in args.ids]
    variants = inject.flag_variants()
    targeting_errs = inject.flag_targeting_errors()
    problems = {s.id: scenarios.validate(s, variants, targeting_errs) for s in chosen}
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        print(json.dumps(problems, indent=1))
        return 2
    summaries = harness.record_all(chosen, sanitize.flag_names(), inject.Injector(), demo_commit=env.demo_commit())
    return 0 if all(s["valid"] for s in summaries) else 1


def _leak_check(args):
    paths = [Path(p) for p in args.paths] or sorted(p for p in config.SNAPSHOTS.glob("incident__*") if p.is_dir())
    if not paths:
        print("no snapshots found: nothing was scanned")
        return 1
    names = sanitize.flag_names()
    found = {}
    for p in paths:
        try:
            hits = sanitize.scan_snapshot(p, names)
        except (OSError, ValueError) as e:  # partial or unreadable snapshot: a problem, keep scanning the rest
            hits = {"error": f"{type(e).__name__}: {e}"}
        if hits:
            found[str(p)] = hits
    print(f"scanned {len(paths)} snapshots; leaks: {json.dumps(found, indent=1) if found else 'none'}")
    return 1 if found else 0


def _revalidate(args, resanitize=False):
    index = Path(config.SNAPSHOTS) / "index.jsonl"
    rows = [json.loads(l) for l in index.read_text(encoding="utf-8").splitlines() if l.strip()] if index.exists() else []
    latest = {r["scenario"]: r for r in rows if r.get("path")}  # later rows overwrite earlier ones
    known = {s.id: s for s in scenarios.load_all()}
    ids = args.ids or [i for i in latest if i in known]
    unknown = [i for i in ids if i not in known or i not in latest]
    if unknown or not ids:
        print(f"unknown or unrecorded scenario ids: {sorted(unknown)}" if unknown else "no recorded snapshots found")
        return 2
    names = sanitize.flag_names()
    all_valid = True
    for i in ids:
        counts = snapshot.resanitize(latest[i]["path"], names) if resanitize else None
        res = snapshot.validate_snapshot(latest[i]["path"], known[i], names)
        harness._write_index_row(Path(config.SNAPSHOTS), {"scenario": i, "path": latest[i]["path"], "valid": res["valid"],
                                                          "leaks": res["leaks"], "revalidated": True})
        if counts:
            print(f"{i}: spans {counts['spans'][0]}->{counts['spans'][1]}, logs {counts['logs'][0]}->{counts['logs'][1]}, "
                  f"valid={res['valid']}")
        else:
            print(f"{i}: valid={res['valid']} (was {latest[i].get('valid')})")
        all_valid &= res["valid"]
    return 0 if all_valid else 1


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except RuntimeError as e:  # includes harness.DirtyStateError / RestoreError
        print(f"error: {e} -- run `python -m rootcause reset-flags` to reset the stack", file=sys.stderr)
        return 3


def _dispatch(args):
    if args.cmd == "up":
        env.compose("up", "-d", "--quiet-pull")
        if _is_dirty():
            print("state is dirty (a previous restore failed): run `python -m rootcause reset-flags` first",
                  file=sys.stderr)
            return 3
        # a fresh stack has no clean 15-minute baseline yet: the first record waits the full cool-down
        harness.mark_restored(time.time(), config.STATE_FILE)
    elif args.cmd == "down":
        env.compose("down")
    elif args.cmd == "status":
        print(json.dumps(env.probe(), indent=1))
    elif args.cmd == "list":
        for s in scenarios.load_all():
            print(f"{s.id:45s} {s.category}")
    elif args.cmd == "reset-flags":
        reset_stack()
        print("stack reset: flags restored, docker pauses/cpu limits undone, cool-down restarted")
    elif args.cmd == "record":
        return _record(args)
    elif args.cmd == "leak-check":
        return _leak_check(args)
    elif args.cmd == "revalidate":
        return _revalidate(args)
    elif args.cmd == "resanitize":
        return _revalidate(args, resanitize=True)
    return 0

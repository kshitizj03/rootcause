"""Command line: manage the demo, list/record scenarios, check snapshots for leaks."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from rootcause import config, env, harness, inject, sanitize, scenarios


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
    return p


def reset_stack(injector=None, run=inject._run):
    """Undo every possible fault (flag file, docker pause/cpu limits), then mark the state clean."""
    injector = injector or inject.Injector(run=run)
    errors = []
    try:
        injector.restore()
    except Exception as e:
        errors.append(str(e))
    undo = {(a["action"], a["container"])
            for s in scenarios.load_all() for a in s.inject.get("docker") or []}
    for action, container in sorted(undo):
        try:
            run(["docker", "unpause", container] if action == "pause"
                else ["docker", "update", "--cpus", "0", container])
        except subprocess.CalledProcessError as e:
            if action == "cpus":  # unpause errors just mean "wasn't paused"
                errors.append(f"cpus undo {container}: {e}")
    if errors:
        raise RuntimeError("reset incomplete: " + "; ".join(errors))
    harness.mark_restored(time.time(), config.STATE_FILE)


def _record(args):
    chosen = scenarios.load_all()
    if not args.all:
        unknown = set(args.ids) - {s.id for s in chosen}
        if unknown or not args.ids:
            print(f"unknown or missing scenario ids: {sorted(unknown)}")
            return 2
        chosen = [s for s in chosen if s.id in args.ids]
    variants = inject.flag_variants()
    problems = {s.id: scenarios.validate(s, variants) for s in chosen}
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        print(json.dumps(problems, indent=1))
        return 2
    summaries = harness.record_all(chosen, sanitize.flag_names(), inject.Injector(), demo_commit=env.demo_commit())
    return 0 if all(s["valid"] for s in summaries) else 1


def _leak_check(args):
    paths = [Path(p) for p in args.paths] or sorted(p for p in config.SNAPSHOTS.glob("*__*") if p.is_dir())
    names = sanitize.flag_names()
    found = {str(p): sanitize.scan_snapshot(p, names) for p in paths}
    found = {k: v for k, v in found.items() if v}
    print(f"scanned {len(paths)} snapshots; leaks: {json.dumps(found, indent=1) if found else 'none'}")
    return 1 if found else 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "up":
        env.compose("up", "-d", "--quiet-pull")
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
    return 0

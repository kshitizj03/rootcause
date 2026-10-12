"""Command line: manage the demo, list/record scenarios, check snapshots for leaks."""
import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

try:
    from openai import OpenAIError  # the Gemini client's base error; the CLI still works without openai installed
except ImportError:
    OpenAIError = ()  # `except ()` catches nothing

from rootcause import config, env, evaluate, harness, heuristic, inject, sanitize, scenarios, snapshot


def _heuristic_solver():
    return "heuristic", heuristic.solve, ()


def _agent_solver():
    from rootcause import agent  # imported lazily: only the agent needs the Gemini client
    # one model per batch (and patient retries, since 503 overloads are common): a per-day quota stops the run (resume tomorrow) instead of silently mixing models in the table
    return agent.NAME, agent.Agent(models=agent.MODELS[:1], attempts=5).solve, (agent.QuotaExhausted,)


def _v1_agent(system, name):
    from rootcause import agent, tools_v1
    return agent.Agent(models=agent.MODELS[:1], attempts=5, toolset=tools_v1, system=system, name=name)


def _agent_v1_solver():
    from rootcause import agent
    return agent.NAME_V1, _v1_agent(agent.SYSTEM_V1, agent.NAME_V1).solve, (agent.QuotaExhausted,)


def _agent_v1_nopriors_solver():
    from rootcause import agent
    return "agent-v1-nopriors", _v1_agent(agent.SYSTEM_V1_NOPRIORS, "agent-v1-nopriors").solve, (agent.QuotaExhausted,)


def _agent_v1_vague_solver():
    from rootcause import agent
    a = _v1_agent(agent.SYSTEM_V1, "agent-v1-vague")
    solve = lambda snap: a.solve({**snap, "meta": {**snap["meta"], "alert": agent.VAGUE_ALERT}})
    return "agent-v1-vague", solve, (agent.QuotaExhausted,)


SOLVERS = {"heuristic": _heuristic_solver, "agent": _agent_solver,
           "agent-v1": _agent_v1_solver, "agent-v1-nopriors": _agent_v1_nopriors_solver,
           "agent-v1-vague": _agent_v1_vague_solver}  # CLI name -> factory of (record name, solve, stop_on)


class _Subparser(argparse.ArgumentParser):
    """Python 3.11's argparse gives a trailing `nargs="*"` positional [] when an option comes between it and the
    previous positional (`eval agent --runs 5 some-id`); intermixed parsing lets options and positionals interleave."""
    _intermixed = False

    def parse_known_args(self, args=None, namespace=None):
        if self._intermixed:  # parse_known_intermixed_args calls back into parse_known_args
            return super().parse_known_args(args, namespace)
        self._intermixed = True
        try:
            return self.parse_known_intermixed_args(args, namespace)
        finally:
            self._intermixed = False


def build_parser():
    p = argparse.ArgumentParser(prog="rootcause")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=_Subparser)
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
    resan.add_argument("--dry-run", action="store_true", help="report what would be dropped; write nothing")
    ev = sub.add_parser("eval", help="run a solver over the recorded snapshots and score it")
    ev.add_argument("solver", choices=list(SOLVERS))
    ev.add_argument("--runs", type=int, default=1)
    ev.add_argument("ids", nargs="*")
    sm = sub.add_parser("summary", help="print the per-category score table for a solver's recorded runs")
    sm.add_argument("solver", choices=list(SOLVERS))
    sm.add_argument("--split", choices=["all", "tune", "heldout"], default="all")
    sub.add_parser("report", help="write docs/results/report.md and figures from all recorded runs")
    mc = sub.add_parser("mcp", help="serve the v1 tools for one snapshot over MCP (stdio)")
    mc.add_argument("path")
    return p


def reset_stack(injector=None, run=inject._run):
    """Undo every possible fault (flag file, docker pause/cpu limits), then mark the state clean."""
    injector = injector or inject.Injector(run=run)
    errors = []
    try:
        injector.restore()
    except Exception as e:
        errors.append(str(e))
    try:
        undo = sorted({(a["action"], a["container"])
                       for s in scenarios.load_all() for a in s.inject.get("docker") or []})
    except Exception as e:  # can't tell which containers scenarios touch: undo every running known target instead
        errors.append(f"scenarios: {e}")
        try:
            running = set(run(["docker", "ps", "--format", "{{.Names}}"]).split())
        except (subprocess.CalledProcessError, OSError) as e:
            errors.append(f"docker ps: {e}")
            running = set()
        undo = sorted((a, t) for t in config.KNOWN_TARGETS if t in running for a in ("pause", "cpus"))
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


def _needs_reset():
    """A failed restore (dirty state) or a flag-file backup left by a killed run means the stack isn't clean."""
    if Path(str(config.FLAGS_FILE) + ".orig").exists():
        return True
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
    dry_run = resanitize and args.dry_run
    latest = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl")
    known = {s.id: s for s in scenarios.load_all()}
    ids = args.ids or [i for i in latest if i in known]
    unknown = [i for i in ids if i not in known or i not in latest]
    if unknown or not ids:
        print(f"unknown or unrecorded scenario ids: {sorted(unknown)}" if unknown else "no recorded snapshots found")
        return 2
    names = sanitize.flag_names()
    all_valid = True
    for i in ids:
        path = latest[i]["path"]
        try:
            counts = snapshot.resanitize(path, names, dry_run=dry_run) if resanitize else None
            if dry_run:
                _print_dry_run(i, counts)
                continue
            res = snapshot.validate_snapshot(path, known[i], names)
        except (OSError, EOFError, ValueError) as e:  # unreadable/corrupt snapshot: report, keep going, no index row
            print(f"{i}: error: {type(e).__name__}: {e}")
            all_valid = False
            continue
        harness._write_index_row(Path(config.SNAPSHOTS), {"scenario": i, "path": path, "valid": res["valid"],
                                                          "leaks": res["leaks"],
                                                          "resanitized" if resanitize else "revalidated": True})
        if resanitize:
            print(f"{i}: spans {counts['spans'][0]}->{counts['spans'][1]}, logs {counts['logs'][0]}->{counts['logs'][1]}, "
                  f"metrics {counts['metrics'][0]}->{counts['metrics'][1]}, valid={res['valid']}")
        else:
            print(f"{i}: valid={res['valid']} (was {latest[i].get('valid')})")
        all_valid &= res["valid"]
    return 0 if all_valid else 1


def _print_dry_run(i, counts):
    print(f"{i}: spans {counts['spans'][0]}->{counts['spans'][1]}, logs {counts['logs'][0]}->{counts['logs'][1]}, "
          f"metrics {counts['metrics'][0]}->{counts['metrics'][1]}")
    for kind, label in (("spans", "name"), ("logs", "body")):
        rows = counts["dropped"][kind]
        if rows:
            by_service = ", ".join(f"{s}={n}" for s, n in Counter(r["service"] for r in rows).most_common())
            print(f"  dropped {kind} by service: {by_service}")
            for text, n in Counter(str(r[label])[:100] for r in rows).most_common(3):
                print(f"    {n}x {text}")


def _eval(args):
    name, solve, stop_on = SOLVERS[args.solver]()
    out = evaluate.run(name, solve, runs=args.runs, ids=args.ids or None, stop_on=stop_on)
    print(f"{out['completed']} new runs" + (f"; stopped: {out['stopped']}" if out["stopped"] else ""))
    _print_summary(name, args.solver)
    if out["stopped"]:
        print("re-run the same command after the quota resets to resume")
        return 4
    return 0


def _print_summary(name, solver, split="all"):
    rows = evaluate.summarise(name, expected=evaluate.expected_counts(split), split=split)
    print(evaluate.format_summary(rows) if rows else f"no runs recorded for {solver} ({split})")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except OpenAIError as e:  # API failure after retries/fallback; the stack is fine, so no reset hint
        print(f"Gemini API error: {e} -- completed runs are kept; re-run the same command to resume", file=sys.stderr)
        return 5
    except RuntimeError as e:  # includes harness.DirtyStateError / RestoreError
        print(f"error: {e} -- run `python -m rootcause reset-flags` to reset the stack", file=sys.stderr)
        return 3


def _dispatch(args):
    if args.cmd == "up":
        env.compose("up", "-d", "--quiet-pull")
        if _needs_reset():
            print("state is dirty (a previous restore failed or the flag file backup is left over): run `python -m rootcause reset-flags` first",
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
    elif args.cmd == "eval":
        return _eval(args)
    elif args.cmd == "summary":
        _print_summary(SOLVERS[args.solver]()[0], args.solver, args.split)
    elif args.cmd == "report":
        from rootcause import report
        print(report.build())
    elif args.cmd == "mcp":
        from rootcause import mcp_server
        return mcp_server.main([args.path])
    return 0

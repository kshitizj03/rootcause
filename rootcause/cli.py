"""Command line: demo stack, scenario recording and checks, evaluation, report/site generation, MCP server."""
import argparse
import copy
import importlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from openai import OpenAI, OpenAIError  # OpenAIError: the model clients' base error

from rootcause import config, evaluate, harness, heuristic, inject, sanitize, scenarios, snapshot, stack
from rootcause.score import Report, make_report, report_to_dict


def _heuristic_solver():
    return "heuristic", heuristic.solve, ()


def slug(model):
    """A model name as a directory-safe suffix: nvidia/nemotron-3-super-120b-a12b -> nvidia-nemotron-3-super-120b-a12b.
    Lower-cased (record names are), without a trailing "." or "-" (Windows drops a trailing "." from directory names)."""
    return re.sub(r"[^a-z0-9._-]", "-", model.lower()).rstrip(".-")


def _pick(base, model, default):
    """(record name, model kwargs): the solver's own model (default()), or the one given to eval with --model, whose
    records go under base@model so they never mix with the built-in batch."""
    return (f"{base}@{slug(model['models'][0])}", model) if model else (base, default())


def _gemini():
    from rootcause import agent  # imported lazily: only the agents need it (and OpenTelemetry)
    # one model per batch: a per-day quota stops the run (resume tomorrow) instead of silently mixing models in the table.
    # The factories below also retry patiently (attempts=5), since 503 overloads are common.
    return {"models": agent.MODELS[:1]}


def _nemotron_kwargs():
    from rootcause import agent  # another model family on NVIDIA's free endpoint (NVIDIA_API_KEY in .env)
    return {"llm": agent.make_nvidia_client(), "models": [agent.NEMOTRON], "provider": "nvidia"}


def _agent_v0_solver(model=None, default=_gemini, base=None):
    from rootcause import agent  # agent v0: naive tools, v0 prompt
    name, model = _pick(base or agent.NAME, model, default)
    kw = {"name": name} if name != agent.NAME else {}  # agent v0 on Gemini keeps the Agent's default name
    return name, agent.Agent(**model, attempts=5, **kw).solve, (agent.QuotaExhausted,)


def _v1(system, base, model, default=_gemini, vague=False, **kw):
    """Agent v1's tools with `system` as the prompt; vague: shown agent.VAGUE_ALERT instead of the scenario's alert."""
    from rootcause import agent, tools_v1
    name, model = _pick(base, model, default)
    solve = agent.Agent(**model, attempts=5, toolset=tools_v1, system=system, name=name, **kw).solve
    return name, _vague(solve) if vague else solve, (agent.QuotaExhausted,)


def _vague(solve):
    """The same solver, shown agent.VAGUE_ALERT instead of the scenario's alert."""
    from rootcause import agent
    return lambda snap: solve({**snap, "meta": {**snap["meta"], "alert": agent.VAGUE_ALERT}})


def _agent_v1_solver(model=None):
    from rootcause import agent
    return _v1(agent.SYSTEM_V1, agent.NAME_V1, model)


def _agent_v1_nopriors_solver(model=None):
    from rootcause import agent
    return _v1(agent.SYSTEM_V1_NOPRIORS, "agent-v1-nopriors", model)


def _agent_v1_vague_solver(model=None):
    from rootcause import agent
    return _v1(agent.SYSTEM_V1, "agent-v1-vague", model, vague=True)


def _agent_v0_nemotron_solver(model=None):
    return _agent_v0_solver(model, _nemotron_kwargs, "agent-v0-nemotron")  # agent v0 exactly, on Nemotron


def _agent_v1_nemotron_solver(model=None):
    from rootcause import agent  # agent-v1 exactly, on Nemotron
    return _v1(agent.SYSTEM_V1, "agent-v1-nemotron", model, _nemotron_kwargs)


def _agent_v1_nemotron_nopriors_solver(model=None):
    from rootcause import agent
    return _v1(agent.SYSTEM_V1_NOPRIORS, "agent-v1-nemotron-nopriors", model, _nemotron_kwargs)


def _agent_v1_nemotron_vague_solver(model=None):
    from rootcause import agent
    return _v1(agent.SYSTEM_V1, "agent-v1-nemotron-vague", model, _nemotron_kwargs, vague=True)


def _agent_v1_nemotron_steps30_solver(model=None):
    from rootcause import agent  # agent v1 on Nemotron with twice the step limit: is the limit what costs accuracy?
    return _v1(agent.SYSTEM_V1, "agent-v1-nemotron-steps30", model, _nemotron_kwargs, max_steps=2 * agent.MAX_STEPS)


# CLI name -> factory of (record name, solve, stop_on). Every factory but the heuristic's takes an optional model
# override ({"llm", "models", "provider"}, from eval --model) that replaces only the model and its client.
SOLVERS = {"heuristic": _heuristic_solver, "agent-v0": _agent_v0_solver,
           "agent-v1": _agent_v1_solver, "agent-v1-nopriors": _agent_v1_nopriors_solver,
           "agent-v1-vague": _agent_v1_vague_solver, "agent-v1-nemotron": _agent_v1_nemotron_solver,
           "agent-v0-nemotron": _agent_v0_nemotron_solver, "agent-v1-nemotron-nopriors": _agent_v1_nemotron_nopriors_solver,
           "agent-v1-nemotron-vague": _agent_v1_nemotron_vague_solver,
           "agent-v1-nemotron-steps30": _agent_v1_nemotron_steps30_solver}


class _Subparser(argparse.ArgumentParser):
    """Python 3.11's argparse gives a trailing `nargs="*"` positional [] when an option comes between it and the
    previous positional (`eval agent-v0 --runs 5 some-id`); intermixed parsing lets options and positionals interleave."""
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
    ev.add_argument("--trace", choices=["off", "otlp", "file"], default="off",
                    help="self-trace the agent with OpenTelemetry GenAI spans (otlp: localhost:4318, file: data/agent_traces.jsonl)")
    ev.add_argument("--model", help="run an agent solver on this model instead of its own (needs --base-url and --key-env)")
    ev.add_argument("--base-url", help="OpenAI-compatible endpoint serving --model")
    ev.add_argument("--key-env", help="name of the environment variable holding the endpoint's API key")
    ev.add_argument("ids", nargs="*")
    cu = sub.add_parser("eval-custom", help="run your own solver (module:function) over the recorded snapshots and score it")
    cu.add_argument("target", help="module:function, importable from the current directory")
    cu.add_argument("--name", required=True, help="record name: data/runs/<name>/")
    cu.add_argument("--runs", type=int, default=1)
    cu.add_argument("ids", nargs="*")
    sm = sub.add_parser("summary", help="print the per-category score table for a solver's recorded runs")
    sm.add_argument("solver", help="a solver name, or any record name under data/runs (e.g. agent-v1@<model>)")
    sm.add_argument("--split", choices=["all", "tune", "heldout"], default="all")
    sub.add_parser("report", help="write docs/results/report.md and figures from all recorded runs")
    sub.add_parser("site", help="write site/data (index + per-incident JSON) for the replay site from all recorded runs")
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
        if not args.ids:
            print("give scenario ids or --all")
            return 2
        unknown = set(args.ids) - {s.id for s in chosen}
        if unknown:
            print(f"unknown scenario ids: {sorted(unknown)}")
            return 2
        chosen = [s for s in chosen if s.id in args.ids]
    variants = inject.flag_variants()
    targeting_errs = inject.flag_targeting_errors()
    problems = {s.id: scenarios.validate(s, variants, targeting_errs) for s in chosen}
    problems = {k: v for k, v in problems.items() if v}
    if problems:
        print(json.dumps(problems, indent=1))
        return 2
    summaries = harness.record_all(chosen, sanitize.flag_names(), inject.Injector(), demo_commit=stack.demo_commit())
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
        harness.write_index_row(Path(config.SNAPSHOTS), {"scenario": i, "path": Path(path).name, "valid": res["valid"],
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
    if counts["duplicate_logs"]:
        print(f"  dropped {counts['duplicate_logs']} exact duplicate logs")
    for kind, label in (("spans", "name"), ("logs", "body")):
        rows = counts["dropped"][kind]
        if rows:
            by_service = ", ".join(f"{s}={n}" for s, n in Counter(r["service"] for r in rows).most_common())
            print(f"  dropped {kind} by service: {by_service}")
            for text, n in Counter(str(r[label])[:100] for r in rows).most_common(3):
                print(f"    {n}x {text}")


def _eval(args):
    provider = None
    if args.trace != "off":  # the OpenTelemetry SDK is imported only when tracing is asked for
        from rootcause import tracing
        provider = tracing.setup(args.trace)  # before the solver (and its agent) is built
    try:
        return _eval_traced(args)
    finally:
        if provider is not None:
            provider.shutdown()


class _Usage(Exception):
    """A command-line mistake: printed, exit 2."""


def _model_override(args):
    """eval --model/--base-url/--key-env -> the agent's model kwargs ({"llm", "models", "provider"}), or None."""
    given = [o for o, v in (("--model", args.model), ("--base-url", args.base_url), ("--key-env", args.key_env)) if v]
    if not given:
        return None
    if args.solver == "heuristic":
        raise _Usage(f"{', '.join(given)}: the heuristic makes no model calls; these options apply to the agent solvers only")
    if len(given) < 3:
        raise _Usage("--model, --base-url and --key-env must be given together")
    if not slug(args.model):
        raise _Usage(f"--model {args.model!r} has no letters or digits to name its records by")
    try:
        url = urllib.parse.urlparse(args.base_url)
        provider = url.hostname
    except ValueError:
        provider = None
    if not provider or url.scheme.lower() not in ("http", "https"):
        raise _Usage(f"--base-url must be an http(s) URL, got {args.base_url!r}")
    if url.scheme.lower() == "http" and provider not in ("localhost", "127.0.0.1", "::1"):
        print(f"warning: --base-url is plain http to {provider}: the API key will be sent unencrypted", file=sys.stderr)
    from rootcause import agent
    key = agent.api_key(args.key_env)  # .env, as for the built-in solvers' keys; MissingKey names the variable only
    # max_retries=0, as for the built-in clients: the agent retries timeouts and 429s itself
    llm = OpenAI(base_url=args.base_url, api_key=key, timeout=120, max_retries=0)
    return {"llm": llm, "models": [args.model], "provider": provider}


def _unknown_ids(ids):
    """Scenario ids that are not in the library or have no recording (evaluate.run would silently skip them)."""
    found = {sid for sid, _, _ in evaluate.targets(ids)} if ids else set()
    return sorted(i for i in ids if i not in found)


def _eval_traced(args):
    from rootcause import agent
    try:
        model = _model_override(args)
        if unknown := _unknown_ids(args.ids):
            print(f"unknown or unrecorded scenario ids: {unknown}")
            return 2
        if model:
            name, solve, stop_on = SOLVERS[args.solver](model)
            solve = _tagged(solve, provider=model["provider"])  # the endpoint's host only: a URL can carry keys in its query
        else:
            name, solve, stop_on = SOLVERS[args.solver]()
        return _run_batch(name, solve, args, stop_on)
    except agent.MissingKey as e:  # raised when a client is built: at the factory, or at the first model request
        raise _Usage(str(e)) from e


def _tagged(solve, **tags):
    """The same solver, with tags added to every record's info (they win over the solver's own keys)."""
    def tagged(snap):
        report, info = solve(snap)
        return report, {**info, **tags}
    return tagged


def _run_batch(name, solve, args, stop_on=()):
    out = evaluate.run(name, solve, runs=args.runs, ids=args.ids or None, stop_on=stop_on)
    print(f"{out['completed']} new runs" + (f"; stopped: {out['stopped']}" if out["stopped"] else ""))
    _print_summary(name, name)
    if out["stopped"]:
        print("re-run the same command after the quota resets to resume")
        return 4
    return 0


NAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9._@-]*[a-z0-9])?")  # no trailing "." or "-": Windows drops a trailing "."


def _load_target(target):
    """module:function, imported with the current directory on the path."""
    module, _, func = target.partition(":")
    if not module or not func:
        raise _Usage(f"target must be module:function, got {target!r}")
    if os.getcwd() not in sys.path:  # `python -m` adds it; the installed `rootcause` script does not
        sys.path.insert(0, os.getcwd())
    try:
        fn = getattr(importlib.import_module(module), func)
    except (ImportError, AttributeError) as e:
        raise _Usage(f"cannot load {target}: {type(e).__name__}: {e}")
    if not callable(fn):
        raise _Usage(f"{target} is not a function")
    return fn


class SolverError(Exception):
    """A custom solver raised, or returned something other than (report, info): printed, exit 1."""


def custom_solver(fn):
    """Wrap fn(snapshot) -> (report, info) so its report goes through the same validation as the agent's answers: a
    score.Report or a dict, either way through make_report, and an invalid one scores as insufficient_evidence with the
    error kept in parse_error. fn gets a copy of the snapshot, so it cannot change what the evidence check reads."""
    def solve(snap):
        try:
            out = fn(copy.deepcopy(snap))
        except OpenAIError:  # an API failure keeps its own exit code and resume hint
            raise
        except Exception as e:
            raise SolverError(f"your solver raised {type(e).__name__}: {e}") from e
        if not (isinstance(out, tuple) and len(out) == 2):
            raise SolverError(f"your solver must return (report, info), got {type(out).__name__}")
        report, info = out
        try:
            info = dict(info or {})
        except (TypeError, ValueError) as e:
            raise SolverError(f"your solver's info must be a dict, got {type(info).__name__}") from e
        try:
            report = make_report(report_to_dict(report) if isinstance(report, Report) else report)
        except (ValueError, TypeError, AttributeError) as e:
            info["parse_error"] = str(e)
            report = Report("insufficient_evidence")
        return report, info
    return solve


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _eval_custom(args):
    if (not NAME_RE.fullmatch(args.name) or args.name.split("@")[0] in SOLVERS
            or args.name in evaluate.EXPERIMENT_SOLVERS or args.name.split(".")[0] in WINDOWS_RESERVED):
        raise _Usage(f"--name must match {NAME_RE.pattern}, and must not be a built-in solver or experiment name or a "
                     f"built-in solver's name followed by @, got {args.name!r}")
    old = next(iter(sorted((Path(evaluate.RUNS_DIR) / args.name).glob("*.json"))), None)
    if old and (prev := json.loads(old.read_text(encoding="utf-8")).get("target")) != args.target:
        raise _Usage(f"data/runs/{args.name}/ holds records of {prev or 'another solver'}, not {args.target}: "
                     f"choose another --name")
    fn = _load_target(args.target)
    if unknown := _unknown_ids(args.ids):
        print(f"unknown or unrecorded scenario ids: {unknown}")
        return 2
    return _run_batch(args.name, _tagged(custom_solver(fn), solver=args.name, target=args.target), args)


def _print_summary(name, solver, split="all"):
    rows = evaluate.summarise(name, expected=evaluate.expected_counts(split), split=split)
    print(evaluate.format_summary(rows) if rows else f"no runs recorded for {solver} ({split})")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except _Usage as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except evaluate.NoValidSnapshot as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except SolverError as e:  # the user's own code failed: no stack reset or API retry would help
        print(f"error: {e} -- completed runs are kept", file=sys.stderr)
        return 1
    except OpenAIError as e:  # API failure after retries/fallback; the stack is fine, so no reset hint
        print(f"model API error: {e} -- completed runs are kept; re-run the same command to resume", file=sys.stderr)
        return 5
    except RuntimeError as e:  # includes harness.DirtyStateError / RestoreError
        print(f"error: {e} -- run `python -m rootcause reset-flags` to reset the stack", file=sys.stderr)
        return 3


def _dispatch(args):
    if args.cmd == "up":
        stack.compose("up", "-d", "--quiet-pull")
        if _needs_reset():
            print("state is dirty (a previous restore failed or the flag file backup is left over): run `python -m rootcause reset-flags` first",
                  file=sys.stderr)
            return 3
        # a fresh stack has no clean 15-minute baseline yet: the first record waits the full cool-down
        harness.mark_restored(time.time(), config.STATE_FILE)
    elif args.cmd == "down":
        stack.compose("down")
    elif args.cmd == "status":
        print(json.dumps(stack.probe(), indent=1))
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
    elif args.cmd == "eval-custom":
        return _eval_custom(args)
    elif args.cmd == "summary":
        # a built-in solver's records are under its own name: no factory call, so no model client and no API key
        if args.solver in SOLVERS or args.solver in evaluate.recorded_solvers():
            _print_summary(args.solver, args.solver, args.split)
        else:
            raise _Usage(f"no solver and no records called {args.solver!r}; built-in solvers: {', '.join(SOLVERS)}")
    elif args.cmd == "report":
        from rootcause import report
        print(report.build())
    elif args.cmd == "site":
        from rootcause import site
        print(site.build())
    elif args.cmd == "mcp":
        from rootcause import mcp_server
        return mcp_server.main([args.path])
    return 0

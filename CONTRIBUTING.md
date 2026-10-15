# Contributing

Fixes, new scenarios and new solvers are welcome. The one rule above the others: **report failures as plainly as wins.** A scenario that would not validate, a solver that scored below the heuristic, a run that went wrong: write it down with the evidence, as `scenarios/NOTES.md` and `docs/results/` do.

## Development setup

Python 3.11. Docker is needed only to record new incidents.

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # (bin/python on macOS/Linux)
.venv/Scripts/python -m pip install -e .                                            # optional: the `rootcause` command
```

Keys go in `.env` in the repository root (`GEMINI_API_KEY`, `NVIDIA_API_KEY`). It is git-ignored, and so are `data/`, `vendor/` and the generated `site/data/` and `site/figures/`. Never commit any of them.

## Running the tests

```bash
.venv/Scripts/python -m pytest -q
```

The suite is offline: no Docker, no API key and no recorded data. Tests build what they need in temporary directories. One test is skipped unless the demo is checked out under `vendor/opentelemetry-demo`. CI runs the same command on Python 3.11.

Every change in behaviour comes with a test that fails without it.

## Adding a scenario

A scenario is one YAML file in `scenarios/`; the file name is its id. For example, `scenarios/payment-failure-50.yaml`:

```yaml
category: easy
alert: "Customers report that some orders are failing at checkout."
inject: {flags: {paymentFailure: "50%"}}
truth: {causes: [{accept: [payment], fault_type: errors}]}
checks:
  - {service: payment, signal: error_ratio, at_least: 0.2}
```

| Field | Rules (enforced by `scenarios.validate` before anything is recorded) |
|---|---|
| `category` | `easy`, `hard-cross-service`, `hard-silent`, `hard-noisy`, `hard-two-faults` or `control` |
| `alert` | a user-visible symptom. It must not be empty, must not mention a flag name, and must not name a root-cause service (spaces, dashes and plurals are caught too). |
| `inject.flags` | `{flag: variant}`. The flag and variant must exist in the demo's `demo.flagd.json`, and the flag's targeting must be a shape the injector can override. |
| `inject.docker` | a list of `{action: pause, container}` or `{action: cpus, container, value}`, on a container in `config.KNOWN_TARGETS` |
| `truth.causes` | a list of `{accept: [services], fault_type: errors \| latency \| resource}`. Every accepted service must be in `config.KNOWN_TARGETS`. A control has `causes: []`, and only a control may. |
| `checks` | proof the fault really showed up: a list of `{service (or "*"), signal, at_least / at_most / ratio_at_least, stat: mean \| max}`. The signal is one of the metric signals or `restarts`, and `ratio_at_least` needs a signal with a floor in `signals.FLOORS`. Every non-control scenario needs at least one check. |
| `settle_s` | optional; how long the fault runs before capture (default 300 s) |

Then:

1. Check out the demo (see the README), then run `python -m rootcause up` and `python -m rootcause record <id>`. This takes about 24 minutes: an 18-minute cool-down, 5 minutes of fault and 1 minute of ingest lag. A recording counts only if every check passes and the leak scan is clean.
2. Run `python -m rootcause leak-check` over the snapshots. If the demo announces your fault in its own telemetry (a log line naming the fault, a flag-named attribute), fix the sanitiser in `rootcause/sanitize.py` with a test. Then re-clean the stored snapshots with `python -m rootcause resanitize` (try `--dry-run` first).
3. Add the outcome to `scenarios/NOTES.md`, including the observed signal (baseline → fault) and the snapshot directory. A scenario that failed or was replaced goes in the dropped table, with the evidence. If you change a check after recording, re-score it with `python -m rootcause revalidate <id>` and say why in the corrections table. Never lower a threshold below a change that is plainly visible.

`config.HELDOUT` is frozen, so a new scenario joins the tuning split.

## Adding a built-in solver

1. Write a factory in `rootcause/cli.py` that returns `(record name, solve, stop_on)` and add it to `SOLVERS`. `solve(snap)` takes what `snapshot.load` returns and gives back `(score.Report, info dict)`. `stop_on` lists the exceptions that should stop a batch cleanly (for a model client: `agent.QuotaExhausted`).
2. An agent variant takes the optional `model` override, as the existing factories do (`_pick`), so `eval --model` works with it.
3. Add the name to `evaluate.SOLVER_ORDER` (a test checks the two lists match). If its batch is planned for other than 5 runs per incident, add it to `evaluate.PLANNED_RUNS`. Give it a label in `SOLVERS` in `site/assets/app.js`. If it should be compared with another solver, add the pair to `report.PAIRS`.
4. An ablation changes exactly one thing. Add a test, like those in `tests/test_ablations.py`, showing that every other `Agent` argument matches the solver it is compared with.

To try a solver without changing the code, use `eval-custom` ([`docs/benchmark.md`](docs/benchmark.md)).

## Code style

- Match the surrounding code: plain functions, small modules and the standard library first. Add no dependency that a few lines can replace.
- Comments and docstrings say why, not what.
- Keep commits small, one change each, with a message that says what changed and why.
- The scoring rules in `rootcause/score.py` and the held-out split are fixed. A change to either makes old and new results incomparable, so it needs a very good reason, stated in the commit and in the results.

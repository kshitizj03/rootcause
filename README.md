# RootCause

An LLM agent that investigates microservice incidents. Given a symptom ("customers report orders failing at checkout"), it queries OpenTelemetry metrics, traces and logs through tools and names the service and fault type behind it, citing evidence that is checked against the telemetry.

RootCause is mainly a **benchmark**: is an LLM agent actually better than a simple rule, and where? Every answer is scored against ground truth on 20 recorded incidents. The scoring rules were fixed before the first run, there are no-fault controls, each agent batch is planned for 5 runs per incident (3 for the Gemini ablations), and a held-out split is kept out of tuning (one exception, disclosed under Provenance in the report).

> **Status, as of 2026-10-15.** Everything is built; not every agent batch is finished yet.
> - **Complete:** the heuristic; agent v1 on Nemotron (100 runs); agent v0 on Nemotron; the no-priors ablation on Nemotron.
> - **Running:** the vague-alert ablation on Nemotron.
> - **Partial:** agent v0 on Gemini (32/100 runs) and agent v1 on Gemini (64/100 runs), paused while the Nemotron batches ran.
> - **Queued:** the Gemini ablations.
>
> The numbers are in [`docs/results/report.md`](docs/results/report.md), which marks partial batches as partial. Two small decision models, Laya and Hunch, both scored below the heuristic zero-shot, so no small-model-then-agent cascade was built ([`laya.md`](docs/results/laya.md), [`hunch.md`](docs/results/hunch.md)).

## How it works

```
 OpenTelemetry Demo (28 services, Docker)
   │  inject a fault (feature flag / docker pause / CPU cap) ─► wait ─► capture ─► restore
   ▼
 incident snapshot  (metrics series + sanitised traces + sanitised logs; ground truth stored separately)
   │
   ├─► heuristic baseline ── "which service's fault signal rose most?"
   └─► LLM agent (Gemini or Nemotron) ── tool loop: top_changes, service_map, search_traces, search_logs, ...
              │                                    (same tools also served over MCP)
              ▼
   report {verdict, ranked causes, evidence[], confidence}
              │
   score (fixed rules) + evidence check (do the cited metrics, traces and log lines exist?)
```

**1. Incident library.** There are 20 scenarios: 16 faults plus 4 no-fault controls, each injected once, live, into the [OpenTelemetry Demo](https://github.com/open-telemetry/opentelemetry-demo) and recorded as a self-contained snapshot. The fault categories are:
- **easy:** one loud fault;
- **cross-service:** the symptom shows up in a different service from the cause;
- **silent:** latency or resource faults with no errors;
- **noisy:** a real fault plus a decoy traffic flood;
- **two-fault:** both causes must be named.

Before a recording counts, metric checks confirm the fault really showed up. [`scenarios/NOTES.md`](scenarios/NOTES.md) records every outcome, including the scenarios that were dropped and why.

**2. Leak-proofing.** Faults are injected through the demo's feature flags, and the demo's own telemetry repeatedly names them: flag evaluation events, the flag service's traces, flag names in log lines, an attribute whose value is `true` only during one fault, Envoy's `DI` ("delay injected") marker, timing quirks in metadata, and alert wording. Each channel was found and closed, and all of them are listed in `scenarios/NOTES.md`.

The automated leak scan checks every snapshot's metrics, spans and logs, which covers the first five channels. The timing quirk and the alert wording were fixed by migrating the snapshots and rewriting the alerts. The snapshots an agent sees contain no scenario names, no flag vocabulary and no ground truth.

**3. Solvers.**
- **Heuristic:** ranks every service's error ratio, p95 latency, peak memory, CPU and restarts by how much each rose compared with a 15-minute baseline. It names the top one. Its threshold was fixed in advance.
- **Agent v0:** a model tool loop with naive tools (raw metric series, trace and log search).
- **Agent v1:** the same loop with change-aware tools (`top_changes`, `service_health`, `service_map`) and structured, checkable evidence.
- **Ablations of agent v1,** each changing one thing: *no priors* drops the two generic sentences from the prompt ("the service the alert mentions is often NOT the cause", "it is possible that nothing is actually wrong"), and *vague alert* gives every incident the same alert, "Users report that something is wrong with the shop." Both are implemented: on Nemotron, no-priors is complete and vague-alert is running; the Gemini runs are queued.

The agents run on two model families, both at temperature 0: Gemini 3.5 Flash-Lite (free tier) and Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`, NVIDIA's free trial endpoint). One model is pinned per batch, so results never mix models.

**4. Scoring.** The rules were written before any run (`rootcause/score.py`):
- top-ranked cause in the accepted set;
- partial credit on two-fault scenarios;
- `no_incident` is the only right answer on a control;
- abstaining counts as wrong.

Two outputs show the measures, as means across runs (accuracy also with its spread across runs):
- `python -m rootcause summary <solver>` prints, per category, accuracy, top-3, fault type (cause and type both right), false alarms, abstentions and the evidence measures;
- [`docs/results/report.md`](docs/results/report.md) has accuracy per category, false alarms, abstentions, evidence, cost, the paired comparisons and the step-limit table.

The two evidence measures are:
- **grounded:** the cited metric, trace or log line exists in the incident window;
- **distinctive:** it also points at something anomalous.

## Replay site

A static site replays every recorded run, failures included:
- **The scoreboard** shows one mark per run, for every incident and solver.
- **Each incident page** steps through the agent's investigation: every tool call and what it returned, drawn as tables and sparklines. Next to it is the verdict against the true cause, the simple rule's answer for the same incident, and the cited evidence marked grounded or not.

![Scoreboard: one mark per run for each incident and solver](docs/images/scoreboard.png)

![Replay of a held-out incident agent v1 on Nemotron got wrong: it ranked the symptom service, cart, above the paused valkey-cart](docs/images/replay.png)

*(Screenshots from 2026-10-15: the Gemini batches are still partial; empty tiles are runs not done yet.)*

```bash
python -m rootcause report && python -m rootcause site   # regenerate figures and site/data from data/runs (see Data below)
python -m http.server 8000 -d site                       # then open http://localhost:8000
```

The site is plain HTML, CSS and JS with no build step, and every URL is relative, so it can be served from any sub-path. To publish it on GitHub Pages, copy the built `site/` (including the generated, git-ignored `site/data/` and `site/figures/`) into a `gh-pages` branch:

```bash
git worktree add --orphan -b gh-pages ../rootcause-pages     # first time only (git 2.42+)
git -C ../rootcause-pages rm -rq --ignore-unmatch .            # drop files from the last publish
cp -r site/. ../rootcause-pages/ && touch ../rootcause-pages/.nojekyll
git -C ../rootcause-pages add -A && git -C ../rootcause-pages commit -m "Publish replay site" && git -C ../rootcause-pages push origin gh-pages
```

The site shows ground truth, so it is built after scoring and is never given to the agent or the MCP server.

## Quick start

Requirements: Windows, macOS or Linux, Python 3.11, Docker (about 4 GB RAM for the demo), and, for agent runs only, a free [Gemini API key](https://aistudio.google.com/) and/or a free [NVIDIA API key](https://build.nvidia.com/).

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # (bin/python on macOS/Linux)
.venv/Scripts/python -m pytest -q                                                   # offline test suite
```

**Data.** The recorded snapshots (16 MB) and run records (15 MB) are not in this repository. The commands that read `data/` (`eval`, `summary`, `report`, `site` and `mcp`) need incidents recorded first with `python -m rootcause record` (below).

**Score the solvers on the recorded snapshots.** Put the keys in `.env`: `GEMINI_API_KEY=...` for the Gemini solvers, and `NVIDIA_API_KEY=...` for the `*-nemotron` solvers.

```bash
python -m rootcause eval heuristic
python -m rootcause eval agent-v1 --runs 5          # resumable; stops cleanly on the daily free-tier quota
python -m rootcause eval agent-v1-nemotron --runs 5
python -m rootcause summary agent-v1 --split heldout
```

**Record new incidents** with the demo checked out under `vendor/opentelemetry-demo`, at the commit the recordings used:

```bash
git clone https://github.com/open-telemetry/opentelemetry-demo vendor/opentelemetry-demo && git -C vendor/opentelemetry-demo checkout cbaf761
python -m rootcause up && python -m rootcause record --all   # ~24 min per scenario (cool-down + fault + capture)
python -m rootcause leak-check
```

**Serve the tools over MCP** (any MCP client). This serves one snapshot's v1 tools over stdio, with the incident's alert as the server instructions:

```bash
python -m rootcause mcp data/snapshots/incident__<stamp>
```

In a client config, use absolute paths, with the venv's python as `command` and `["-m", "rootcause.mcp_server", "<abs snapshot dir>"]` as `args`. Set `cwd` to the repository root. Don't point an interactive session at a held-out snapshot (`config.HELDOUT`), because that contaminates the held-out split.

## Repository layout

| Path | What |
|---|---|
| `rootcause/cli.py`, `__main__.py`, `config.py` | command line (`python -m rootcause ...`) and project-wide settings |
| `rootcause/stack.py`, `backends.py`, `signals.py` | the demo's Docker Compose stack; Prometheus, Jaeger and OpenSearch clients; per-service signals and scenario checks |
| `rootcause/inject.py`, `harness.py`, `snapshot.py` | fault injection with guaranteed restore, cool-down, capture |
| `rootcause/sanitize.py` | leak filters and the leak scanner |
| `rootcause/scenarios.py`, `scenarios/` | scenario definitions and validation rules; the YAML files and `NOTES.md` |
| `rootcause/score.py`, `evaluate.py` | report validation, scoring, resumable runs, per-category summaries |
| `rootcause/summary.py`, `heuristic.py` | baseline-vs-fault change table and the heuristic |
| `rootcause/tools_v0.py`, `tools_v1.py`, `agent.py` | agent tools (v0, v1) and the model tool loop (Gemini or NVIDIA) |
| `rootcause/evidence.py`, `mcp_server.py` | evidence checker and MCP server |
| `rootcause/report.py`, `tracing.py` | results report and figures; optional OpenTelemetry GenAI spans of agent runs |
| `rootcause/site.py`, `site/` | data builder and static front end of the replay site |
| `tests/` | offline test suite (no Docker, no API key, no recorded data) |
| `experiments/laya/`, `experiments/hunch/` | decision-model entry tests: can a small model beat the heuristic? |
| `infra/` | Compose override that pins the observability backends to fixed host ports |
| `docs/results/` | results: `report.md` and its figures, the Laya and Hunch entry tests, the interim heuristic-vs-agent-v0 write-up |

## Honest limits

- **Twenty incidents from one demo app on one laptop.** This is a small benchmark, not a general claim.
- **Every solver gets the exact fault onset** (t=0 is the injection time), and several alerts hint at the culprit's functional area. The vague-alert ablation is meant to measure how much that helps (running on Nemotron, queued on Gemini).
- **Two free models only:** Gemini 3.5 Flash-Lite (free tier) and Nemotron 3 Super (NVIDIA's free trial endpoint), both at temperature 0. The spread across runs measures API nondeterminism, not sampling, and two models say little about how others would do.

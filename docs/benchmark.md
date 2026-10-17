# Benchmarking your own model or agent

This page is for anyone who wants to score their own model, or their own diagnosis agent, on the RootCause incidents. It describes what a solver is given, what it must return, how the answer is scored, and the rules that keep the numbers honest.

**You need recorded incidents.** The snapshots are not in this repository yet. Record them with the demo first (see the README's Quick start: `python -m rootcause up`, then `record --all`, then `leak-check`). Every command below reads `data/snapshots/`.

## What a snapshot contains

Each recorded incident is a directory `data/snapshots/incident__<UTC time of the injection>/`, for example `incident__20261002T160026Z`. The name carries no scenario id. `data/snapshots/index.jsonl` maps scenario ids to directories; for each scenario, the newest valid row (every check passed, no leaks) is the one used.

| File | Contents | Given to solvers |
|---|---|---|
| `meta.json` | the alert and the time windows | yes |
| `metrics.json` | per-service and per-container metric series | yes |
| `spans.jsonl.gz` | sanitised trace spans, one JSON object per line | yes |
| `logs.jsonl.gz` | sanitised log lines, one JSON object per line | yes |
| `truth.json` | the answer: accepted services and fault type per cause, scenario id, category | **no** |
| `validation.json` | the scenario's signal checks against this recording, and the leak scan | **no** |

### meta.json

| Field | Meaning |
|---|---|
| `alert` | the user-visible symptom, one sentence (for example "Sponsored banners intermittently fail to show on the storefront.") |
| `fault_start` | Unix time in seconds of the injection: t = 0 (on a control, nothing is injected at t = 0) |
| `baseline_start` | `fault_start - 900`: the 15 fault-free minutes before t = 0 |
| `end` | `fault_start` + the scenario's `settle_s` (300 s for all current scenarios): the end of the fault window |
| `demo_commit` | the OpenTelemetry Demo commit the incident was recorded on |

### metrics.json

`{signal: {name: [[unix_seconds, value], ...]}}`, one point every 15 s from `baseline_start` to `end`. Points whose value is not finite are dropped, and a service with no data has no series.

| Signal | Keyed by | What it is (PromQL in `rootcause/signals.py`) |
|---|---|---|
| `rps` | service | span calls per second (3-minute rate) |
| `error_ratio` | service | share of span calls with error status |
| `p95_ms` | service | 95th-percentile span duration, ms |
| `mem_mb` | container | memory use, MB |
| `cpu_cores` | container | CPU use, cores |
| `uptime_s` | container | uptime, s; a drop is a restart |

The service signals cover the 16 traced services in `config.APP_SERVICES`. The container signals also cover the untraced dependencies kafka, valkey-cart and astronomy-db (`config.INFRA_CONTAINERS`). flagd, flagd-ui and load-generator never appear: flagd would reveal the fault, and load-generator is the demo's synthetic users.

### spans.jsonl.gz

One span per line:

```json
{"trace_id": "b122...", "span_id": "1e7a...", "parent_id": "a092...", "service": "accounting", "name": "receive orders",
 "start_ms": 1790956843367.3, "dur_ms": 48.47, "error": false, "message": "",
 "attributes": {"messaging.destination.name": "orders"}, "events": [{"name": "...", "attributes": {}}]}
```

- `start_ms` is Unix time in milliseconds and `dur_ms` is the duration in milliseconds.
- `error` is true when the span's status is an error, and `message` is the status message.
- `parent_id` is `""` on a root span. `attributes` is a flat key/value dict.

For each traced service, up to 50 traces were fetched for each of two windows: the 5 minutes before t = 0, and t = 0 to `end`. Whole traces come back, so they include other services' spans, and some spans start outside those windows: some up to about 60 s past `end`, and some start well before it (up to hours earlier). Spans are de-duplicated by `span_id`.

### logs.jsonl.gz

One log line per line:

```json
{"ts": "2026-10-02T15:59:34.6199779Z", "service": "accounting", "severity": "Information", "severity_number": 9,
 "body": "Order details: {@OrderResult}.", "trace_id": "5c50..."}
```

- `ts` is an ISO-8601 UTC string.
- `severity` is the text the service wrote; `severity_number` is the OpenTelemetry number (9 INFO, 13 WARN, 17 ERROR). Either can be null.
- `trace_id` is `""` when the line has none.

Logs were fetched for the 19 services and containers in `config.KNOWN_TARGETS`, with up to 200 lines per service for each of the two windows, newest first. So a busy service's pre-alert lines cover only the last seconds before t = 0. Exact duplicates are dropped.

### Sanitising

Before storage, spans and logs pass through `rootcause/sanitize.py`:
- the hidden services are dropped;
- feature-flag attributes and events, and any key naming a flag, are removed;
- Envoy's `DI`/`FI` fault markers are rewritten out;
- any span or line that still mentions the injection is dropped.

`python -m rootcause leak-check` scans every snapshot for anything left over. [`scenarios/NOTES.md`](../scenarios/NOTES.md) lists every leak channel that was found and closed.

## What a solver may read: the tool boundary

A solver gets exactly what `snapshot.load` returns: a dict with `meta`, `metrics`, `spans` and `logs`, read from the four files marked "yes" above. It never gets `truth.json`, `validation.json`, `index.jsonl`, the scenario YAML files or `scenarios/NOTES.md`, all of which name the answer. `evaluate.run` reads `truth.json` only after the solver has returned.

- **The built-in agents** see the alert as their first message ("ALERT (fired at t=0): ...") and read the snapshot only through their tools:
  - agent v0 (`rootcause/tools_v0.py`): `list_services`, `get_metric`, `search_traces`, `get_trace`, `search_logs`;
  - agent v1 (`rootcause/tools_v1.py`): those, plus `top_changes`, `service_health` and `service_map`.

  Tool times are seconds relative to t = 0. `python -m rootcause mcp <snapshot dir>` serves the v1 tools for one snapshot to any MCP client.
- **A custom solver** (`eval-custom`, below) receives the same dict. It runs in the same process, though, so nothing stops it from opening other files. Keeping to the boundary is up to you. A result from a solver that read anything else is not comparable with the others.

## The report a solver returns

```json
{"verdict": "incident",
 "causes": [{"service": "payment", "fault_type": "errors"}],
 "evidence": [{"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "0.03 -> 0.31"}],
 "confidence": 0.8}
```

It is validated by `score.make_report`, the same function the agents' answers go through:

- `verdict` is one of `incident`, `no_incident` or `insufficient_evidence`. Case and surrounding spaces are ignored.
- `confidence` is a number. Values outside 0-1 are clipped, a missing value counts as 0, and a boolean is an error.
- `causes` must be a non-empty list on an incident and is ignored otherwise.
  - Only the first 3 causes are kept, most likely first.
  - Each cause needs a string `service` and a `fault_type` of `errors`, `latency` or `resource`.
  - Service names are lower-cased, and spaces and underscores become `-`.
- `evidence` is a list of up to 20 items (a single item is wrapped in a list). It is optional. Each item is one of:
  - a string, kept as free text;
  - a metric item: `{"kind": "metric", "service", "signal", "claim"}`;
  - a trace item: `{"kind": "trace", "trace_id", "service" (optional), "claim"}`;
  - a log item: `{"kind": "log", "service", "quote"}`.

  A dict missing a required field is kept as text. Claims and quotes are cut to 500 characters.

An answer that fails validation scores as `insufficient_evidence` (an abstention), and the error is stored in the record's `parse_error`. The agents get one repair turn first; a custom solver does not.

## Scoring

The rules are in `rootcause/score.py` and were fixed before the first scoring run. Each run gets:

- **On a control** (no true cause):
  - `correct` is 1 only for `no_incident`;
  - `false_alarm` is set when the verdict is `incident`;
  - `insufficient_evidence` is wrong and counts as an abstention.
- **On a one-cause incident:**
  - `correct` is 1 when the **first** cause's service is in the accepted list, and 0 otherwise. Some incidents accept more than one service; image-slow-load, for example, accepts frontend-proxy or image-provider.
  - `top3` is set when any of the (up to 3) causes is accepted.
  - `fault_type_ok` is set when the first cause is correct and its fault type matches too.
- **On a two-fault incident:**
  - each true cause is matched to a different reported cause, in any position;
  - `correct` is the fraction of true causes found (0, 0.5 or 1);
  - `top3` is set when both are found;
  - `fault_type_ok` is set when both are found with the right fault types.
- **On any incident,** a verdict other than `incident` scores 0. `no_incident` is simply wrong, and `insufficient_evidence` is wrong and counts as an abstention. Abstaining never earns credit.

Every record also gets an evidence check (`rootcause/evidence.py`). Neither measure proves the cited fact caused the incident.

- **Grounded:** the cited item exists.
  - A metric item needs a series with both a before and an after window.
  - A trace item needs the trace to have spans at t >= 0 (and, when a service is given, spans of that service).
  - A log item needs a line of that service at t >= 0 containing the quote, ignoring case, with runs of whitespace treated as one space. The quote must be at least 8 characters.
- **Distinctive:** the item is grounded and also points at something anomalous.
  - A metric must have changed by at least 0.5 in the change score that `top_changes` shows.
  - A trace must hold an error span, or a span slower than its service's pre-alert p95.
  - A log quote must appear in no pre-alert line of that service.

Free-text evidence is neither grounded nor distinctive.

## Splits and honest use

`config.HELDOUT` holds 6 scenarios, frozen on 2026-10-13 before any agent-v1 tuning: the alphabetically last scenario of each category. The other 14 are the tuning split. `summary --split tune|heldout|all` and the report show each split.

The rules this repository follows, and that a comparable result needs:

- **No tuning on held-out.** Develop your prompt, tools or model choice on the tuning split. Do not look at held-out snapshots, transcripts or scores until you are done. Do not point an interactive MCP session at a held-out snapshot. Then run the held-out split as it is, and report it separately. If you looked anyway, say so, as the report does under Provenance.
- **Report every run.** Records are kept, and a re-run resumes rather than replaces, so a bad run cannot quietly disappear. Report all the records you made, not your best batch, and not a re-run of only the incidents that went wrong. Use the same `--runs` for every incident; the agent batches here are planned for 5 runs (3 for the Gemini ablations).
- **Controls count.** The 4 no-fault controls are in every table. An agent that always cries "incident" scores 0 on them, and its false alarms are shown. A result that leaves them out is not comparable.

## Running a model behind the built-in agents: `eval --model`

Any OpenAI-compatible chat endpoint with tool calling can stand in for an agent's model:

```bash
python -m rootcause eval agent-v1 --model nvidia/nemotron-3-super-120b-a12b \
    --base-url https://integrate.api.nvidia.com/v1 --key-env NVIDIA_API_KEY --runs 5
python -m rootcause summary agent-v1@nvidia-nemotron-3-super-120b-a12b --split heldout
```

- **What changes.** `--model`, `--base-url` and `--key-env` replace only the solver's model and its client. The prompt, tools, step limit, retries, temperature (0) and alert handling stay as they are.
- **Solvers.** The options work with `agent-v0`, `agent-v1`, the agent-v1 ablations and the `*-nemotron*` solvers. The example above runs agent v1 exactly as `agent-v1-nemotron` does, under another record name. The heuristic makes no model calls, so the options are an error there.
- **Key.** `--key-env` names an environment variable that holds the key (`.env` in the repository root is read too). A missing variable is an error that names it; its value is never printed.
- **Where records go.** Records go to `data/runs/<solver>@<model>/`. The model name is lower-cased, every character outside `a-z0-9._-` becomes `-`, and a trailing `.` or `-` is dropped (Windows drops a trailing `.` from directory names). So they never mix with the built-in batches, and a re-run of the same command resumes. Each record's `provider` is the endpoint's host name; the URL itself is never stored, since it can carry a key in its query.
- **Plain http.** `--base-url` must be `http://` or `https://`; the case of the scheme does not matter. Plain `http://` to a host other than `localhost`, `127.0.0.1` or `::1` prints a warning: the API key is sent unencrypted.
- **Planned runs.** `<solver>@<model>` is planned like its base solver: 5 runs, or 3 for `agent-v1-vague` and `agent-v1-nopriors`.
- **Throttling and retries.** Requests are spaced at least 4.5 s apart, for any provider. A 429 whose message says the limit is per day ends the batch cleanly (exit 4; re-run the same command later to resume). Any other 429, a 5xx, a timeout or a connection error is tried up to 5 times in all, with waits of 15, 30, 60 and 120 s. If that does not help, the command exits 5 and keeps the completed runs.

## Running your own agent: `eval-custom`

Write a function that takes the snapshot dict and returns `(report, info)`:

```python
def solve(snap):            # snap = {"meta": ..., "metrics": ..., "spans": ..., "logs": ...}
    ...
    return {"verdict": "no_incident", "causes": [], "evidence": [], "confidence": 0.5}, {}
```

[`examples/my_agent.py`](../examples/my_agent.py) is a short baseline: it names the service whose error ratio rose most. Run it from the repository root:

```bash
python -m rootcause eval-custom examples.my_agent:solve --name my-agent --runs 5
python -m rootcause summary my-agent
```

- **TARGET** is `module:function`, imported with the current directory on the path.
- **The snapshot** your function gets is a copy: changing it does not change what the evidence check reads.
- **The report** may be a `score.Report` or a dict as above. Both forms are validated as described under "The report a solver returns": a `Report` is turned into a dict and goes through `score.make_report` too, so, for example, a `Report` with 19 causes keeps its first 3 and a confidence of 7.0 becomes 1.0.
- **`info`** is any JSON-serialisable dict, stored in each record. The report and the site read a few keys from it when present:
  - `requests`, `prompt_tokens` and `completion_tokens` (all three) for the cost table;
  - `turns` for the step-limit table;
  - `error` for the errors column;
  - `transcript`, a list of `{"tool", "args", "output"}`, for the replay.
- **`--name`** must match `[a-z0-9](?:[a-z0-9._@-]*[a-z0-9])?`: lower case, and no trailing `.` or `-`. It must not be a built-in solver name, a built-in solver name followed by `@`, or the name of one of the decision-model experiments (`laya-multilingual`, `laya-english`, `hunch-1.7b`, `hunch-0.6b`). A name whose directory already holds records from another TARGET is refused too, so two solvers never share one name.
- **Where records go.** Records go to `data/runs/<name>/` through the same `evaluate.run` as the built-in solvers, with the same scoring, evidence check and truth isolation. Each record also gets `solver` (the name) and `target` (TARGET).
- **`code`** in every record is RootCause's own git commit (short sha, with `-dirty` when tracked files had uncommitted changes), not a version of your solver.
- **Resuming.** A re-run resumes. An exception raised by your function stops the batch with exit code 1 and the message `your solver raised <Type>: <message>`; the runs completed so far are kept. (An `openai.OpenAIError` keeps the model-API exit code, 5.)

## Reading the results

`eval`, `eval-custom` and `summary` print one table per solver:

| Column | Meaning |
|---|---|
| category | the incident category, then "all incidents" (every non-control) |
| scenarios | scenarios with records; `n/m` when some of the library's `m` have none |
| runs | records per scenario; `lo-hi` when a batch is uneven (stopped part-way) |
| accuracy (mean +/- sd) | mean over scenarios of each scenario's mean `correct`; sd across run indices that cover every scenario |
| top-3 | as above for `top3` (not shown for controls) |
| fault type (cause+type) | `fault_type_ok` |
| false alarm | `false_alarm`, controls only |
| abstain | share of `insufficient_evidence` answers |
| grounded, distinctive | share of cited items, among records that cited any |
| errors | share of records with an `error` (for the agents: a conversation the endpoint rejected); `-` when the solver never sets `error` |

On a two-fault row, accuracy is the fraction of causes found, and top-3 means both were found.

`python -m rootcause report` writes `docs/results/report.md` and `python -m rootcause site` builds the replay site. Both include every solver with records: the built-in ones first, in a fixed order, then any other (yours, or `<solver>@<model>`) sorted by name. A directory under `data/runs/` whose name starts with `_` (for example `_discarded`) is never a solver. The Laya and Hunch decision-model tests (`laya-*`, `hunch-*`) are experiments, not agents: they are in the report's tables but not on the site.

- The report marks a batch with fewer than its planned runs on some incident as partial. 5 is the planned number for a solver that is not built in; a `<solver>@<model>` batch follows its base solver's plan.
- The run-to-run agreement and calibration sections cover every solver with a stated confidence and more than one run on some incident.
- The paired comparisons and the figures cover the built-in solvers only.
- The accuracy-vs-coverage notes cover solver names that start with `agent`.

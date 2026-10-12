# Week 4: Ablations, Evaluation Report and Agent Self-Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the spec's ablation variants, compute accuracy-vs-coverage and token cost, generate one evaluation report (tables plus charts) comparing every solver by category and split, and trace the agent's own LLM and tool calls with OpenTelemetry GenAI spans.

**Architecture:**
- **Ablations** are new `SOLVERS` entries that reuse `agent.Agent`, with a prompt without priors and a fixed vague alert. Nothing about the agent loop changes.
- **`evaluate.py`** gains pure functions over stored records: `coverage_curve` and `usage`.
- **`report.py`** reads every solver's records and writes `docs/results/report.md` plus PNG charts (matplotlib, Agg backend).
- **`tracing.py`** configures an OpenTelemetry SDK provider (OTLP/HTTP to the demo's collector, or a JSONL file). The agent emits spans through the OpenTelemetry API, which is a no-op unless tracing is configured, and takes an injectable `tracer` for tests.

**Tech Stack:** Python 3.11, matplotlib 3.10, opentelemetry-api/sdk 1.x with opentelemetry-exporter-otlp-proto-http, pytest. Install with `PIP_CACHE_DIR=D:/rootcause/.cache/pip`.

**Spec:** `docs/superpowers/specs/2026-09-25-rootcause-design.md`, sections 10 (evaluation report, ablations, accuracy-vs-coverage, tokens) and 12 (self-tracing). Weeks 1–3 code: `rootcause/*`.

## Global Constraints

- Everything stays under `D:\rootcause`; `data/` is git-ignored. Use `.venv/Scripts/python.exe` with Git Bash on Windows.
- Gemini free tier only (`gemini-3.5-flash-lite`). **The Flash vs Flash-Lite ablation is dropped:** Flash's free tier is 20 requests/day and an agent run takes about 10. The report must say so.
- Ablations change exactly one thing relative to `agent-v1`:
  - `agent-v1-nopriors` removes the two prior sentences ("…often NOT the cause…" and "It is possible that nothing is actually wrong.");
  - `agent-v1-vague` replaces every alert with `VAGUE_ALERT = "Users report that something is wrong with the shop."`.
  - Both use the v1 toolset, one model, and `attempts=5`.
- Held-out discipline: the report shows `all`, `tune` and `heldout` separately. Ablations never change v1's prompt or tools.
- **Tool boundary is unchanged:** solvers see only `snapshot.load` data. Tracing must never export snapshot contents, tool outputs or prompts. It exports only names, ids, counts, model names and timings.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **A solver with no records, or a split with none** (e.g. an ablation not yet run). The report must still build and show "not run" instead of crashing or showing 0.00. Tested in Task 3.
2. **Coverage curve edge cases:**
   - all records abstained gives an empty curve;
   - every record at the same confidence gives one point;
   - controls count like any other record.

   Tested in Task 2.
3. **Tracing off by default.** With no `ROOTCAUSE_TRACE`, the agent must behave and perform exactly as before, with no exporter, no network and no files. Tested in Task 4.
4. **The OTLP endpoint is down** while tracing is on. The run must not fail or hang (export is best-effort and batched). Tested in Task 4.
5. **The vague-alert wrapper must not mutate the loaded snapshot** that `evaluate.run` passes to the evidence checker. Tested in Task 1.

## File Structure

```
rootcause/agent.py       + SYSTEM_V1_NOPRIORS, VAGUE_ALERT; Agent(tracer=...) emits GenAI spans
rootcause/cli.py         + SOLVERS agent-v1-nopriors / agent-v1-vague; `report` command; eval --trace {off,otlp,file}
rootcause/evaluate.py    + coverage_curve(records), usage(records), load_records(solver, split)
rootcause/report.py      build(solvers, out_dir) -> report.md + figures/*.png
rootcause/tracing.py     setup(mode, path=None) -> TracerProvider | None
requirements.txt         + matplotlib, opentelemetry-sdk, opentelemetry-exporter-otlp-proto-http
tests/test_ablations.py, test_report.py, test_tracing.py (+ evaluate tests)
docs/results/report.md + docs/results/figures/   (Task 5)
```

---

### Task 1: Ablation solvers

**Files:**
- Modify: `rootcause/agent.py`, `rootcause/cli.py`
- Test: `tests/test_ablations.py`

**Interfaces:**
- `agent.SYSTEM_V1_NOPRIORS` is `SYSTEM_V1` with both prior sentences removed, via `_replace_once`.
- `agent.VAGUE_ALERT` (str).
- `SOLVERS["agent-v1-nopriors"]()` returns `("agent-v1-nopriors", solve, (QuotaExhausted,))`.
- `SOLVERS["agent-v1-vague"]()` returns `("agent-v1-vague", solve, …)`. Its `solve(snap)` calls the v1 agent on a *copy* of the snapshot whose `meta.alert` is `VAGUE_ALERT`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ablations.py`:
```python
from rootcause import agent, cli, tools_v1


def test_nopriors_prompt_removes_exactly_the_two_prior_sentences():
    p = agent.SYSTEM_V1_NOPRIORS
    assert "often NOT the cause" not in p and "nothing is actually wrong" not in p
    assert "top_changes" in p and '"kind": "metric"' in p  # v1 tools hint and evidence format kept
    removed = len(agent.SYSTEM_V1) - len(p)
    assert 0 < removed < 260


class FakeAgent:
    seen = []

    def __init__(self, **kw):
        self.kw = kw

    def solve(self, snap):
        FakeAgent.seen.append((self.kw, snap["meta"]["alert"]))
        return "report", {}


def test_ablation_solvers_change_one_thing(monkeypatch):
    monkeypatch.setattr(agent, "Agent", FakeAgent)
    FakeAgent.seen.clear()
    snap = {"meta": {"alert": "Orders fail at checkout."}, "metrics": {}, "spans": [], "logs": []}
    for name in ("agent-v1-nopriors", "agent-v1-vague"):
        record_name, solve, stop_on = cli.SOLVERS[name]()
        assert record_name == name and stop_on == (agent.QuotaExhausted,)
        solve(snap)
    (kw_np, alert_np), (kw_v, alert_v) = FakeAgent.seen
    assert kw_np["system"] == agent.SYSTEM_V1_NOPRIORS and alert_np == "Orders fail at checkout."
    assert kw_v["system"] == agent.SYSTEM_V1 and alert_v == agent.VAGUE_ALERT
    assert kw_np["toolset"] is tools_v1 and kw_v["toolset"] is tools_v1
    assert kw_np["models"] == kw_v["models"] == agent.MODELS[:1]
    assert snap["meta"]["alert"] == "Orders fail at checkout."  # the loaded snapshot is never mutated
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ablations.py -q`
Expected: FAIL (`SYSTEM_V1_NOPRIORS` missing; `KeyError: 'agent-v1-nopriors'`).

- [ ] **Step 3: Implement**

In `rootcause/agent.py`, after `SYSTEM_V1`:
```python
# Ablations of v1 (each changes exactly one thing)
SYSTEM_V1_NOPRIORS = _replace_once(_replace_once(
    SYSTEM_V1,
    "The alert describes a user-visible symptom; the service it mentions is often NOT the cause, so follow errors "
    "and latency to where they originate. ", ""),
    "It is possible that nothing is actually wrong. ", "")
VAGUE_ALERT = "Users report that something is wrong with the shop."
```
In `rootcause/cli.py`:
```python
def _v1_agent(system, name):
    from rootcause import agent, tools_v1
    return agent.Agent(models=agent.MODELS[:1], attempts=5, toolset=tools_v1, system=system, name=name)


def _agent_v1_nopriors_solver():
    from rootcause import agent
    return "agent-v1-nopriors", _v1_agent(agent.SYSTEM_V1_NOPRIORS, "agent-v1-nopriors").solve, (agent.QuotaExhausted,)


def _agent_v1_vague_solver():
    from rootcause import agent
    a = _v1_agent(agent.SYSTEM_V1, "agent-v1-vague")
    solve = lambda snap: a.solve({**snap, "meta": {**snap["meta"], "alert": agent.VAGUE_ALERT}})
    return "agent-v1-vague", solve, (agent.QuotaExhausted,)
```
- Register both in `SOLVERS`.
- If `_agent_v1_solver` builds its `Agent` the same way, refactor it to use `_v1_agent(agent.SYSTEM_V1, agent.NAME_V1)`, so there is one construction site.

- [ ] **Step 4: Run tests**

Run `tests/test_ablations.py` and `tests/test_cli.py`, then the full suite with `-W error`. Expected: all pass. If the 260-character bound fails, print the removed length and check that both sentences, and nothing else, were removed. Adjust the bound only to the measured length plus a small margin.

- [ ] **Step 5: Commit**

```bash
git add rootcause/agent.py rootcause/cli.py tests/test_ablations.py
git commit -m "Add ablation solvers: v1 without priors, v1 with a vague alert

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Coverage curve and usage statistics

**Files:**
- Modify: `rootcause/evaluate.py`
- Test: extend `tests/test_evaluate.py`

**Interfaces:**
- `load_records(solver_name, out_dir=RUNS_DIR, split=None) -> list[dict]` is the record loading that `summarise` already does, extracted. `summarise` calls it, so there is one loader.
- `coverage_curve(records) -> list[dict]`. For each distinct confidence `t` in descending order:
  - `covered` is the records whose verdict is not `insufficient_evidence` and whose `report.confidence >= t`;
  - each point is `{"threshold": t, "coverage": len(covered)/len(records), "accuracy": mean(score.correct over covered)}`.

  An empty input, or all abstained, gives `[]`. This is record-level, not scenario-balanced; the docstring says so.
- `usage(records) -> dict | None`: `{"runs", "requests_mean", "requests_max", "prompt_tokens_mean", "completion_tokens_mean", "tokens_per_correct"}`. `tokens_per_correct` is the sum of (prompt + completion) divided by the sum of `correct`, or None if no correct. It returns None when no record has `prompt_tokens`, as for the heuristic.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_evaluate.py`)

```python
def rec(conf, correct, verdict="incident", p=1000, c=50, req=5):
    return {"scenario": "s", "category": "easy", "run": 0, "requests": req, "prompt_tokens": p,
            "completion_tokens": c, "report": {"verdict": verdict, "confidence": conf},
            "score": {"correct": correct}}


def test_coverage_curve_thresholds_descend_and_skip_abstentions():
    recs = [rec(0.9, 1.0), rec(0.9, 0.0), rec(0.5, 1.0), rec(0.2, 0.0, verdict="insufficient_evidence")]
    pts = evaluate.coverage_curve(recs)
    assert [p["threshold"] for p in pts] == [0.9, 0.5]
    assert pts[0] == {"threshold": 0.9, "coverage": 0.5, "accuracy": 0.5}
    assert pts[1]["coverage"] == 0.75 and abs(pts[1]["accuracy"] - 2 / 3) < 1e-9


def test_coverage_curve_edge_cases():
    assert evaluate.coverage_curve([]) == []
    assert evaluate.coverage_curve([rec(0.4, 0.0, verdict="insufficient_evidence")]) == []
    assert evaluate.coverage_curve([rec(0.95, 1.0), rec(0.95, 1.0)]) == [{"threshold": 0.95, "coverage": 1.0, "accuracy": 1.0}]


def test_usage_and_tokens_per_correct():
    u = evaluate.usage([rec(0.9, 1.0, p=1000, c=50, req=4), rec(0.9, 0.0, p=3000, c=150, req=8)])
    assert u == {"runs": 2, "requests_mean": 6.0, "requests_max": 8, "prompt_tokens_mean": 2000.0,
                 "completion_tokens_mean": 100.0, "tokens_per_correct": 4200.0}
    assert evaluate.usage([{"score": {"correct": 1.0}}]) is None  # heuristic records carry no usage


def test_load_records_respects_split(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    d = tmp_path / "x"
    d.mkdir()
    for sid in ("a", "b"):
        (d / f"{sid}__0.json").write_text(json.dumps({"scenario": sid, "category": "easy", "run": 0,
                                                       "score": {"correct": 1.0}}))
    assert [r["scenario"] for r in evaluate.load_records("x", tmp_path, split="tune")] == ["a"]
```

- [ ] **Step 2: Run them to verify they fail**

Expected: `AttributeError` for `coverage_curve`, `usage` and `load_records`.

- [ ] **Step 3: Implement** (in `rootcause/evaluate.py`)

```python
def load_records(solver_name, out_dir=RUNS_DIR, split=None):
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(out_dir) / solver_name).glob("*.json"))]
    return [r for r in recs if in_split(r["scenario"], split)]


def coverage_curve(records):
    """Accuracy when only answers at or above a confidence threshold count (record-level, not scenario-balanced).
    Abstentions (insufficient_evidence) are never covered."""
    if not records:
        return []
    answered = [r for r in records if r["report"]["verdict"] != "insufficient_evidence"]
    points = []
    for t in sorted({r["report"]["confidence"] for r in answered}, reverse=True):
        covered = [r for r in answered if r["report"]["confidence"] >= t]
        points.append({"threshold": t, "coverage": len(covered) / len(records),
                       "accuracy": sum(r["score"]["correct"] for r in covered) / len(covered)})
    return points


def usage(records):
    recs = [r for r in records if "prompt_tokens" in r]
    if not recs:
        return None
    correct = sum(r["score"]["correct"] for r in recs)
    tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in recs)
    return {"runs": len(recs), "requests_mean": _mean(r["requests"] for r in recs),
            "requests_max": max(r["requests"] for r in recs),
            "prompt_tokens_mean": _mean(r["prompt_tokens"] for r in recs),
            "completion_tokens_mean": _mean(r["completion_tokens"] for r in recs),
            "tokens_per_correct": tokens / correct if correct else None}
```
Change `summarise` to obtain its records via `load_records(solver_name, out_dir, split)`, removing its own glob and filter, so there is one loader.

- [ ] **Step 4: Run tests.** Run `tests/test_evaluate.py` and `tests/test_splits.py`, then the full suite with `-W error`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/evaluate.py tests/test_evaluate.py
git commit -m "Add accuracy-vs-coverage curve, usage statistics and a single record loader

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Evaluation report generator

**Files:**
- Create: `rootcause/report.py`
- Modify: `rootcause/cli.py` (`report` command), `requirements.txt` (`matplotlib>=3.8`)
- Test: `tests/test_report.py`

**Interfaces:**
- `report.SOLVER_ORDER = ["heuristic", "agent-v0", "agent-v1", "agent-v1-nopriors", "agent-v1-vague"]`.
- `report.build(out_dir=config.ROOT / "docs" / "results", runs_dir=evaluate.RUNS_DIR, solvers=SOLVER_ORDER) -> Path` writes `out_dir/report.md` and `out_dir/figures/{accuracy_by_category,coverage}.png`, and returns the path of `report.md`.
- `report.md` sections:
  1. **Accuracy by category**: one table per split (`all`, `tune`, `heldout`). Rows are categories plus "all incidents"; columns are solvers; each cell is `mean ± sd` or "not run".
  2. **False alarms and abstentions**: the control false-alarm rate and incident abstain rate per solver (`all` split).
  3. **Evidence**: grounded and distinctive per solver (`all` split).
  4. **Cost**: the `usage()` table per solver.
  5. **Per-scenario accuracy**: scenarios × solvers, marking held-out scenarios with `*`.
  6. **Accuracy vs coverage**: the figure, and one sentence per agent solver with its accuracy at 50% coverage, from the nearest curve point.
  7. **Not run**: lists solvers with no records. A fixed paragraph explains why Flash vs Flash-Lite is absent (the 20 requests/day free tier).
- **Charts:**
  - `matplotlib.use("Agg")` is set before importing pyplot.
  - `accuracy_by_category.png` is a grouped bar chart: categories × solvers that have records, `all` split, with sd error bars where available.
  - `coverage.png` plots accuracy against coverage for each agent solver with records.
  - Before writing the chart code, read the `dataviz` skill and follow its palette and labelling rules: a readable title, axis labels with units, one consistent colour per solver across both charts, and no chart junk.
- CLI: `python -m rootcause report` calls `build()` and prints the path.

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:
```python
import json

from rootcause import config, report, scenarios


def write(runs, solver, sid, cat, k, correct, conf=0.8, tokens=True):
    d = runs / solver
    d.mkdir(parents=True, exist_ok=True)
    r = {"scenario": sid, "category": cat, "run": k,
         "report": {"verdict": "incident" if cat != "control" else "no_incident", "confidence": conf},
         "score": {"correct": correct, "top3": True, "fault_type_ok": None if cat == "control" else True,
                   "false_alarm": False, "abstained": False},
         "evidence_check": {"grounded": 1, "distinctive": 1, "total": 1}}
    if tokens:
        r.update(requests=5, prompt_tokens=1000, completion_tokens=50)
    (d / f"{sid}__{k}.json").write_text(json.dumps(r))


def test_build_writes_markdown_and_figures_and_marks_missing_solvers(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("c",))
    monkeypatch.setattr(scenarios, "load_all", lambda: [scenarios.Scenario("a", "easy", "x", {}, {}, []),
                                                        scenarios.Scenario("c", "control", "x", {}, {}, [])])
    runs = tmp_path / "runs"
    write(runs, "heuristic", "a", "easy", 0, 1.0, tokens=False)
    write(runs, "heuristic", "c", "control", 0, 1.0, tokens=False)
    for k in range(2):
        write(runs, "agent-v1", "a", "easy", k, float(k), conf=0.9 - k / 10)
        write(runs, "agent-v1", "c", "control", k, 1.0)
    path = report.build(out_dir=tmp_path / "out", runs_dir=runs, solvers=["heuristic", "agent-v1", "agent-v1-vague"])
    md = path.read_text(encoding="utf-8")
    for heading in ("Accuracy by category", "False alarms", "Evidence", "Cost", "Per-scenario", "coverage", "Not run"):
        assert heading.lower() in md.lower()
    assert "agent-v1-vague" in md.split("Not run")[1] and "20 requests" in md
    assert "| c* |" in md or "c*" in md  # held-out scenarios are marked
    assert (tmp_path / "out" / "figures" / "accuracy_by_category.png").stat().st_size > 1000
    assert (tmp_path / "out" / "figures" / "coverage.png").stat().st_size > 1000


def test_build_with_no_records_at_all_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, "load_all", lambda: [])
    path = report.build(out_dir=tmp_path / "out", runs_dir=tmp_path / "runs", solvers=["heuristic"])
    assert "not run" in path.read_text(encoding="utf-8").lower()
```

- [ ] **Step 2: Run them to verify they fail.** Expected: `ModuleNotFoundError: rootcause.report`. Install matplotlib first: `PIP_CACHE_DIR=D:/rootcause/.cache/pip .venv/Scripts/python.exe -m pip install "matplotlib>=3.8"`.

- [ ] **Step 3: Implement `rootcause/report.py`**

Write the module to the interface above using only these existing helpers:
- `evaluate.summarise(name, runs_dir, expected, split)` for the category tables;
- `evaluate.load_records`;
- `evaluate.coverage_curve`;
- `evaluate.usage`;
- `evaluate.in_split`.

For `expected` counts, use `scenarios.load_all()` filtered with `in_split`, as `cli._print_summary` does. Move that helper into `evaluate` (`expected_counts(split)`) and use it from both places, so there is one copy.

Format numbers with two decimals. Missing values print "-", and solvers with no records print "not run". Keep the module around 150 lines: one function per section, plus `build`.

- [ ] **Step 4: Wire the CLI.** Add `sub.add_parser("report", help="write docs/results/report.md and figures from all recorded runs")`, with the dispatch `elif args.cmd == "report": from rootcause import report; print(report.build()); return 0`. Add `matplotlib>=3.8` to `requirements.txt`.

- [ ] **Step 5: Run tests.** Run `tests/test_report.py`, then the full suite with `-W error`. Expected: all pass, with no matplotlib warnings (use Agg).

- [ ] **Step 6: Commit**

```bash
git add rootcause/report.py rootcause/evaluate.py rootcause/cli.py requirements.txt tests/test_report.py
git commit -m "Add evaluation report generator (tables by split, evidence, cost, per-scenario, coverage) with charts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Agent self-tracing (OpenTelemetry GenAI spans)

**Files:**
- Create: `rootcause/tracing.py`
- Modify: `rootcause/agent.py` (spans), `rootcause/cli.py` (`eval --trace {off,otlp,file}`), `requirements.txt`
- Test: `tests/test_tracing.py`

**Interfaces:**
- Install: `PIP_CACHE_DIR=D:/rootcause/.cache/pip .venv/Scripts/python.exe -m pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http`, and add both to `requirements.txt`.
- `tracing.setup(mode, path=None) -> TracerProvider | None`:
  - `"off"` returns None and changes nothing.
  - `"otlp"` builds a `TracerProvider(resource={"service.name": "rootcause-agent"})` with `BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces", timeout=2))`, sets it globally and returns it.
  - `"file"` is the same but exports JSON lines to `path`, defaulting to `data/agent_traces.jsonl`, through a small `SpanExporter` subclass that writes `span.to_json()` per line.
- `Agent(..., tracer=None)` uses `tracer or opentelemetry.trace.get_tracer("rootcause.agent")`. That is a no-op unless a provider was set.
- **Spans**, following the GenAI semantic conventions. **Attributes never carry prompts, tool arguments or outputs.**
  - The root span `invoke_agent <name>` has `gen_ai.operation.name=invoke_agent` and `gen_ai.agent.name`. At the end it gets `rootcause.verdict` and `rootcause.requests`.
  - Each successful model request gets a child `chat <model>` with:
    - `gen_ai.operation.name=chat`
    - `gen_ai.provider.name=gcp.gemini`
    - `gen_ai.request.model`
    - `gen_ai.response.model` (the served model)
    - `gen_ai.usage.input_tokens`
    - `gen_ai.usage.output_tokens`
  - A failed attempt sets the span status to ERROR and records the exception *type* only.
  - Each tool call gets a child `execute_tool <name>` with `gen_ai.operation.name=execute_tool` and `gen_ai.tool.name`.
- CLI: `eval --trace {off,otlp,file}`, default `off`, calls `tracing.setup(mode)` before solving. Call `provider.shutdown()` at the end. A `BatchSpanProcessor` with a 2 s exporter timeout means a dead endpoint only loses spans.

- [ ] **Step 1: Write the failing tests**

`tests/test_tracing.py`:
```python
import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rootcause import agent, tracing
from tests_agent_fakes import FINAL, SNAP, Msg, make_llm, tool_call  # see Step 3: shared fakes module


def traced_agent(script):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    a = agent.Agent(llm=make_llm(script), min_interval=0, sleep=lambda s: None, clock=lambda: 0.0,
                    tracer=provider.get_tracer("test"))
    return a, exporter


def test_spans_follow_genai_conventions_without_content():
    a, exporter = traced_agent([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content=FINAL)])
    a.solve(SNAP)
    spans = {s.name: s for s in exporter.get_finished_spans()}
    root = spans["invoke_agent agent-v0"]
    chats = [s for s in exporter.get_finished_spans() if s.name.startswith("chat ")]
    tool = spans["execute_tool list_services"]
    assert root.attributes["gen_ai.operation.name"] == "invoke_agent" and root.attributes["rootcause.verdict"] == "incident"
    assert len(chats) == 2 and chats[0].attributes["gen_ai.usage.input_tokens"] == 100
    assert chats[0].attributes["gen_ai.provider.name"] == "gcp.gemini"
    assert tool.attributes["gen_ai.tool.name"] == "list_services"
    assert all(s.parent.span_id == root.context.span_id for s in chats + [tool])
    dumped = json.dumps([dict(s.attributes) for s in exporter.get_finished_spans()])
    assert "Orders fail" not in dumped and "points" not in dumped  # no prompt / tool output content


def test_tracing_off_is_a_noop():
    assert tracing.setup("off") is None


def test_file_mode_writes_json_lines(tmp_path):
    provider = tracing.setup("file", path=tmp_path / "t.jsonl", set_global=False)
    with provider.get_tracer("t").start_as_current_span("x"):
        pass
    provider.shutdown()
    lines = (tmp_path / "t.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["name"] == "x"


def test_otlp_mode_with_dead_endpoint_does_not_hang(monkeypatch):
    import time
    provider = tracing.setup("otlp", endpoint="http://127.0.0.1:9/v1/traces", set_global=False)
    t = time.monotonic()
    with provider.get_tracer("t").start_as_current_span("x"):
        pass
    provider.shutdown()
    assert time.monotonic() - t < 15
```
`setup` therefore also takes `endpoint=` and `set_global=True` keyword arguments (defaults as specified), so the tests don't touch the global provider.

- [ ] **Step 2: Run them to verify they fail.** Expected: `ModuleNotFoundError` for `rootcause.tracing` (and `tests_agent_fakes`).

- [ ] **Step 3: Implement**
- **Shared fakes.** Move the agent test fakes (`Msg`, `tool_call`, `resp`, `FakeLLM` and the `SNAP`/`FINAL` constants) from `tests/test_agent.py` into `tests/tests_agent_fakes.py`. Import them in both test files, so there is no duplication. Add `make_llm(script)`, which returns a `FakeLLM`.
- **`rootcause/tracing.py`:** implement `setup` per the interface. `_JsonlExporter(SpanExporter)` writes `span.to_json(indent=None)` per line and returns `SpanExportResult.SUCCESS`.
- **`rootcause/agent.py`:**
  - Add a `tracer` parameter.
  - Wrap `solve` in the root span.
  - In `_chat`, open a `chat <model>` span per attempt. On success set the attributes; on an exception call `span.set_status(Status(StatusCode.ERROR))` and set `error.type` to the exception class name, then re-raise.
  - Wrap each tool call in `execute_tool <name>`.
  - Keep the existing behaviour byte-for-byte when no provider is configured, since all existing agent tests must pass unchanged.
- **`rootcause/cli.py`:** add `ev.add_argument("--trace", choices=["off", "otlp", "file"], default="off")`. In `_eval`, call `provider = tracing.setup(args.trace)` first and run `provider.shutdown()` in a `finally` if it is not None.

- [ ] **Step 4: Run tests.** Run `tests/test_tracing.py` and `tests/test_agent.py`, then the full suite with `-W error`. Expected: all pass. The dead-endpoint test should finish in a few seconds.

- [ ] **Step 5: Commit**

```bash
git add rootcause/tracing.py rootcause/agent.py rootcause/cli.py requirements.txt tests/
git commit -m "Trace the agent with OpenTelemetry GenAI spans (off by default; OTLP or JSONL), no content exported

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Runs, report and write-up (controller)

- [ ] Run `eval agent-v1 --runs 5` (Week 3), then `eval agent-v1-nopriors --runs 5` and `eval agent-v1-vague --runs 5`, each detached and resumable. These span days on the free tier, so order them v1 → vague → nopriors and record where quota stopped.
- [ ] Smoke-test tracing once: with the demo stack up, run `eval agent-v1 payment-failure-50 --trace otlp` and confirm the `rootcause-agent` service appears in Jaeger (`http://localhost:16686`), with chat and execute_tool spans. Screenshot it for the README.
- [ ] Run `python -m rootcause report`, then read `docs/results/report.md` and both figures by eye, checking every number against `summary <solver> --split ...`.
- [ ] Write `docs/results/week4.md`: what each ablation shows, the held-out numbers first, failures with transcript excerpts, the free-tier limits hit, and the Flash ablation not run.
- [ ] Commit the report, figures and write-up.

**Week 4 is done when** both ablations exist as solvers with tests, the report builds from records alone (including partial ones), self-tracing works and is off by default, and the report plus write-up cover every solver that has records.

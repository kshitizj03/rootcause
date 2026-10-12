# Week 3: Change-Aware Tools, MCP Server, Evidence Checker and Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a held-out split, give the agent change-aware tools served over MCP, check that cited evidence really exists in the snapshot, and compare agent v1 with v0 and the heuristic per category and per split.

**Architecture:**
- **Toolset seam:** a *toolset* is a module with `SCHEMAS` and `call(snap, name, args)`. `tools.py` (v0) gains a `registry` parameter on `call`, so `tools_v1.py` reuses all v0 tools and adds `top_changes`, `service_health` and `service_map`, all built on `summary.changes`.
- **MCP server:** `mcp_server.py` serves any toolset over stdio with the MCP SDK's low-level `Server`. A parity test proves that MCP output equals the in-process output.
- **Evidence:** reports may cite structured evidence (`metric` / `trace` / `log` items). `evidence.py` verifies each item against the snapshot, and `evaluate.run` stores the check in every record.
- **Agent v1:** the existing `Agent` with `toolset=tools_v1` and a prompt asking for structured evidence.

**Tech Stack:** Python 3.11, `mcp` 2.3 (already installed in `.venv`; pinned in requirements), `anyio` (an `mcp` dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-rootcause-design.md`, sections 7, 8, 8b, 9, 10, including the held-out set. Week-2 code is on the same branch line: `rootcause/{score,summary,heuristic,evaluate,tools,agent,cli}.py`.

## Global Constraints

- Everything stays under `D:\rootcause`; `data/` is git-ignored. Run Python as `.venv/Scripts/python.exe`, using Git Bash on Windows. Any pip use sets `PIP_CACHE_DIR=D:/rootcause/.cache/pip`.
- Gemini free tier only, with `gemini-3.5-flash-lite`. Never print, log or commit `GEMINI_API_KEY` (in `.env`).
- **Tool boundary:** toolsets and the MCP server get only `snapshot.load(path)`. `truth.json`, `validation.json`, `index.jsonl`, `scenarios/` and `NOTES.md` must never reach a solver or the MCP server.
- **Held-out split:** frozen before any v1 prompt or tool tuning. It is the alphabetically last scenario of each category: `product-catalog-failure, valkey-cart-paused, recommendation-cache-leak, payment-failure-with-flood, payment-failure-and-recommendation-leak, control-4`. These are never used to tune v1, and they are reported separately.
- The scoring rules (spec 8b) are unchanged. Grounded evidence is a separate metric and never changes accuracy.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **Free-form evidence from the model.** Evidence items may be strings, objects with unknown `kind`, objects missing fields, numbers or nulls. Normalisation must never raise for a well-formed report. A string becomes `{"kind": "text"}`, which counts as not grounded. Tested in Task 3.
2. **Over-long or broad citations.** A log quote shorter than 8 characters, or a trace id that exists but belongs to a different service, must not count as grounded. Tested in Task 3.
3. **Change tools on sparse data.** A service with no baseline, a snapshot with no spans or with root spans only, and an unknown service in `service_health` all return valid, useful JSON. Tested in Task 2.
4. **MCP server on bad input.** An unknown tool name or bad arguments return an error text result (never a crashed server). A missing snapshot path exits with a clear message. Tested in Task 5.
5. **Split reporting.** `summary --split heldout` on a solver that has no held-out records says so. Split filters never change the stored records. Tested in Task 1.

## File Structure

```
rootcause/config.py       + HELDOUT (frozen tuple of 6 scenario ids)
rootcause/evaluate.py     summarise(..., split=None); evidence check stored per record; "grounded" column
rootcause/cli.py          summary --split {all,tune,heldout}; SOLVERS["agent-v1"]; `mcp <snapshot-dir>` command
rootcause/tools.py        call(snap, name, raw_args, registry=None)  (v0 behaviour unchanged)
rootcause/tools_v1.py     top_changes, service_health, service_map + all v0 tools; SCHEMAS; call
rootcause/score.py        evidence items: str kept as str; dicts normalised (kind metric|trace|log|text)
rootcause/evidence.py     check(report, snap) -> {"items": [...], "grounded": int, "total": int}
rootcause/heuristic.py    evidence as structured metric items
rootcause/agent.py        SYSTEM_V1, NAME_V1
rootcause/mcp_server.py   build_server(snap, toolset) / serve(path, toolset) over stdio
requirements.txt          + mcp>=2.3
tests/test_splits.py, test_tools_v1.py, test_evidence.py, test_mcp_server.py (+ edits to existing tests)
docs/results/week3.md     v0 vs v1 vs heuristic, tune vs held-out (Task 6)
```

---

### Task 1: Frozen held-out split and split-aware summary

**Files:**
- Modify: `rootcause/config.py`, `rootcause/evaluate.py`, `rootcause/cli.py`
- Test: `tests/test_splits.py`

**Interfaces:**
- Produces:
  - `config.HELDOUT: tuple[str, ...]`;
  - `evaluate.summarise(solver_name, out_dir=RUNS_DIR, expected=None, split=None)`, where `split` is `None|"all"|"tune"|"heldout"` and filters records by scenario id before grouping;
  - CLI `summary <solver> [--split all|tune|heldout]`, defaulting to `all`.
- `expected` counts passed by the CLI must respect the split (count library scenarios in that split per category).

- [ ] **Step 1: Write the failing tests**

`tests/test_splits.py`:
```python
import json

from rootcause import cli, config, evaluate, scenarios


def test_heldout_is_one_scenario_per_category_and_exists():
    lib = {s.id: s.category for s in scenarios.load_all()}
    assert set(config.HELDOUT) <= set(lib)
    cats = [lib[i] for i in config.HELDOUT]
    assert sorted(cats) == sorted(set(lib.values())) and len(cats) == len(set(cats))
    for c in set(lib.values()):  # rule: the alphabetically last scenario of each category
        assert max(i for i, cat in lib.items() if cat == c) in config.HELDOUT


def write(d, sid, cat, correct):
    d.mkdir(parents=True, exist_ok=True)
    score = {"correct": correct, "top3": True, "fault_type_ok": True, "false_alarm": False, "abstained": False}
    (d / f"{sid}__0.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": 0, "score": score}))


def test_summarise_filters_by_split(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HELDOUT", ("b",))
    d = tmp_path / "s"
    write(d, "a", "easy", 1.0)
    write(d, "b", "easy", 0.0)
    rows = lambda split: {r["category"]: r["accuracy_mean"] for r in evaluate.summarise("s", tmp_path, split=split)}
    assert rows("all")["easy"] == 0.5 and rows(None)["easy"] == 0.5
    assert rows("tune")["easy"] == 1.0 and rows("heldout")["easy"] == 0.0


def test_summary_command_reports_empty_split(monkeypatch, capsys):
    monkeypatch.setattr(evaluate, "summarise", lambda *a, **k: [])
    assert cli.main(["summary", "heuristic", "--split", "heldout"]) == 0
    assert "no runs recorded" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_splits.py -q`
Expected: FAIL (`config.HELDOUT` missing; `summarise() got an unexpected keyword argument 'split'`; `--split` unrecognised).

- [ ] **Step 3: Implement**

`rootcause/config.py`, appended:
```python
# Frozen 2026-10-13, before any agent-v1 tuning: the alphabetically last scenario of each category. Never used to
# tune prompts or tools; reported separately from the rest (the tuning set).
HELDOUT = ("product-catalog-failure", "valkey-cart-paused", "recommendation-cache-leak",
           "payment-failure-with-flood", "payment-failure-and-recommendation-leak", "control-4")
```
`rootcause/evaluate.py`: give `summarise` a `split=None` parameter. After loading `recs`, add:
```python
    if split == "tune":
        recs = [r for r in recs if r["scenario"] not in config.HELDOUT]
    elif split == "heldout":
        recs = [r for r in recs if r["scenario"] in config.HELDOUT]
```
`rootcause/cli.py`:
- Add `sm.add_argument("--split", choices=["all", "tune", "heldout"], default="all")` to the `summary` parser.
- `_print_summary(name, solver, split="all")` computes `expected` per category from `scenarios.load_all()`, restricted to the split by the same rule, and calls `evaluate.summarise(name, expected=expected, split=split)`.
- The `summary` dispatch passes `args.split`. `eval` keeps the default `"all"`.
- If `rows` is empty, print `no runs recorded for <solver> (<split>)`.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_splits.py tests/test_evaluate.py tests/test_cli.py -q`, then the full suite with `-W error`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/config.py rootcause/evaluate.py rootcause/cli.py tests/test_splits.py
git commit -m "Freeze the held-out split (one scenario per category) and report tune/held-out separately

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Change-aware toolset (v1)

**Files:**
- Modify: `rootcause/tools.py` (`call` gains `registry=None`)
- Create: `rootcause/tools_v1.py`
- Test: `tests/test_tools_v1.py`

**Interfaces:**
- Consumes: `summary.changes(snap)` rows (`service, signal, baseline, value, score, direction, fault_type`); `tools.TOOLS`, `tools.SCHEMAS`, `tools._sig`, `tools._services`, `tools.MAX_TOOL_CHARS`.
- Produces: `tools_v1.TOOLS` (all v0 tools plus `top_changes`, `service_health`, `service_map`), `tools_v1.SCHEMAS`, `tools_v1.call(snap, name, raw_args)`.
  - `top_changes(snap, n=10, include_load=False)` returns `{"changes": [{"service", "signal", "before", "after", "change"}...], "note"}`. `change` is the relative change score as a signed string such as `"+29.5x"` or `"-0.80x"`. `rps` rows appear only when `include_load` is true. `n` is clamped to 1..40.
  - `service_health(snap, service)` returns `{"service", "signals": [{"signal", "before", "after", "change"}...]}` for every signal of that service. An unknown service returns `{"error", "valid_services"}`.
  - `service_map(snap, limit=20)` returns the caller→callee edges from parent/child spans across services: `{"edges": [{"caller", "callee", "calls_before", "calls_after", "errors_before", "errors_after"}...]}`. Before means `t < 0` and after means `t >= 0`, relative to `fault_start`. Edges are sorted by `errors_after - errors_before`, then `calls_after`, both descending. `limit` is clamped to 1..60.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools_v1.py`:
```python
import json

from rootcause import tools, tools_v1

T0 = 900.0


def series(base, fault):
    return [[float(t), base] for t in range(0, 901, 15)] + [[float(t), fault] for t in range(915, 1215, 15)]


def span(sid, parent, service, t, error=False, trace="t1"):
    return {"trace_id": trace, "span_id": sid, "parent_id": parent, "service": service, "name": "op",
            "start_ms": (T0 + t) * 1000, "dur_ms": 5.0, "error": error, "message": "", "attributes": {}, "events": []}


SNAP = {"meta": {"alert": "a", "baseline_start": 0.0, "fault_start": T0, "end": 1200.0},
        "metrics": {"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)},
                    "rps": {"frontend": series(20.0, 40.0)},
                    "p95_ms": {"payment": series(100.0, 110.0)}},
        "spans": [span("a", "", "checkout", -50), span("b", "a", "payment", -49),
                  span("c", "", "checkout", 10, trace="t2"), span("d", "c", "payment", 11, error=True, trace="t2"),
                  span("e", "d", "payment", 12, trace="t2")],
        "logs": []}


def out(name, args=None):
    return json.loads(tools_v1.call(SNAP, name, args or {}))


def test_v0_call_unchanged_and_v1_includes_v0_tools():
    assert set(tools.TOOLS) <= set(tools_v1.TOOLS)
    assert {"top_changes", "service_health", "service_map"} <= set(tools_v1.TOOLS)
    assert {s["function"]["name"] for s in tools_v1.SCHEMAS} == set(tools_v1.TOOLS)
    assert "error" in json.loads(tools.call(SNAP, "top_changes", {}))  # v0 registry doesn't have it


def test_top_changes_ranks_and_hides_load_by_default():
    r = out("top_changes")
    assert r["changes"][0]["service"] == "payment" and r["changes"][0]["signal"] == "error_ratio"
    assert r["changes"][0]["change"] == "+30.0x" and all(c["signal"] != "rps" for c in r["changes"])
    assert any(c["signal"] == "rps" for c in out("top_changes", {"include_load": True})["changes"])


def test_service_health_lists_every_signal_and_handles_unknown():
    r = out("service_health", {"service": "payment"})
    assert {s["signal"] for s in r["signals"]} == {"error_ratio", "p95_ms"}
    assert "valid_services" in out("service_health", {"service": "nope"})


def test_service_map_counts_cross_service_edges_before_and_after():
    r = out("service_map")
    assert r["edges"] == [{"caller": "checkout", "callee": "payment", "calls_before": 1, "calls_after": 1,
                           "errors_before": 0, "errors_after": 1}]  # same-service edge d->e is not an edge


def test_change_tools_on_sparse_snapshots():
    empty = {"meta": SNAP["meta"], "metrics": {}, "spans": [], "logs": []}
    assert json.loads(tools_v1.call(empty, "top_changes", {})) ["changes"] == []
    assert json.loads(tools_v1.call(empty, "service_map", {}))["edges"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tools_v1.py -q`
Expected: FAIL with `ModuleNotFoundError: rootcause.tools_v1`.

- [ ] **Step 3: Implement**

In `rootcause/tools.py`, change `call` to take a registry, defaulting to v0's (behaviour unchanged):
```python
def call(snap, name, raw_args, registry=None):
    """Run one tool by name; never raises. Returns JSON text capped at MAX_TOOL_CHARS."""
    registry = TOOLS if registry is None else registry
    try:
        if name not in registry:
            out = {"error": f"unknown tool {name!r}", "valid_tools": sorted(registry)}
        else:
            args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args or {})
            out = registry[name](snap, **args)
        text = json.dumps(out)
    except Exception as e:  # model-supplied names/args can fail in many ways (e.g. OverflowError on limit=1e999)
        text = json.dumps({"error": f"bad call to {name!r}: {type(e).__name__}: {e}"})
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS - len(TRUNCATED)] + TRUNCATED
    return text
```

`rootcause/tools_v1.py`:
```python
"""Agent v1 toolset: every v0 tool plus change-aware views (baseline window vs fault window) and a service map.

Reads only a loaded snapshot (meta, metrics, spans, logs). t < 0 is before the alert, t >= 0 after it."""
from collections import defaultdict

from rootcause import summary, tools


def _fmt(row):
    sign = "+" if row["direction"] == "up" else "-"
    return {"service": row["service"], "signal": row["signal"], "before": tools._sig(row["baseline"]),
            "after": tools._sig(row["value"]), "change": f"{sign}{row['score']:.1f}x" if row["score"] >= 10 else f"{sign}{row['score']:.2f}x"}


def top_changes(snap, n=10, include_load=False):
    n = max(1, min(40, int(10 if n is None else n)))
    rows = [r for r in summary.changes(snap) if include_load is True or str(include_load).lower() == "true" or r["signal"] != "rps"]
    return {"changes": [_fmt(r) for r in rows[:n]],
            "note": "change = |after - before| / max(before, small floor); before = 15 min before the alert, after = from 1 min after it"}


def service_health(snap, service):
    rows = [r for r in summary.changes(snap) if r["service"] == service]
    if not rows:
        return {"error": f"no metrics for {service!r}", "valid_services": tools._services(snap)}
    return {"service": service, "signals": [_fmt(r) for r in rows]}


def service_map(snap, limit=20):
    limit = max(1, min(60, int(20 if limit is None else limit)))
    t0 = snap["meta"]["fault_start"] * 1000
    by_id = {s["span_id"]: s for s in snap["spans"]}
    edges = defaultdict(lambda: {"calls_before": 0, "calls_after": 0, "errors_before": 0, "errors_after": 0})
    for s in snap["spans"]:
        parent = by_id.get(s["parent_id"])
        if not parent or parent["service"] == s["service"]:
            continue
        e = edges[(parent["service"], s["service"])]
        when = "after" if s["start_ms"] >= t0 else "before"
        e[f"calls_{when}"] += 1
        e[f"errors_{when}"] += bool(s["error"])
    ranked = sorted(edges.items(), key=lambda kv: (-(kv[1]["errors_after"] - kv[1]["errors_before"]), -kv[1]["calls_after"], kv[0]))
    return {"edges": [{"caller": a, "callee": b, **v} for (a, b), v in ranked[:limit]],
            "note": "edges from parent/child spans across services; before = t < 0, after = t >= 0"}


TOOLS = {**tools.TOOLS, "top_changes": top_changes, "service_health": service_health, "service_map": service_map}
SCHEMAS = tools.SCHEMAS + [
    {"type": "function", "function": {"name": "top_changes", "description": "Start here. Every service's signals ranked by how much they changed from the 15 minutes before the alert to after it (error_ratio, p95_ms, mem_mb peak, cpu_cores, restarts; rps only with include_load).",
                                      "parameters": {"type": "object", "properties": {"n": {"type": "integer"}, "include_load": {"type": "boolean"}}}}},
    {"type": "function", "function": {"name": "service_health", "description": "All signals of one service, before vs after the alert, with the change.",
                                      "parameters": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "service_map", "description": "Which service calls which (from traces), with call and error counts before vs after the alert; edges whose errors rose come first.",
                                      "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}}},
]


def call(snap, name, raw_args):
    return tools.call(snap, name, raw_args, registry=TOOLS)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tools_v1.py tests/test_tools.py -q`, then the full suite with `-W error`.
Expected: all pass. If `test_top_changes...` disagrees on `"+30.0x"`, check: payment error_ratio baseline 0 → floor 0.01, fault 0.3, so the score is 30 and `>= 10` gives one decimal.

- [ ] **Step 5: Commit**

```bash
git add rootcause/tools.py rootcause/tools_v1.py tests/test_tools_v1.py
git commit -m "Add change-aware v1 toolset (top_changes, service_health, service_map) over the v0 tools

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Structured evidence and the evidence checker

**Files:**
- Modify: `rootcause/score.py` (evidence normalisation), `rootcause/heuristic.py` (structured evidence), `rootcause/evaluate.py` (store the check and add a grounded column)
- Create: `rootcause/evidence.py`
- Test: `tests/test_evidence.py`; update `tests/test_heuristic.py`, `tests/test_score.py` and `tests/test_evaluate.py` where needed.

**Interfaces:**
- **Evidence items in `Report.evidence`.** A plain string stays a string. A dict is normalised to one of:
  - `{"kind": "metric", "service": str, "signal": str, "claim": str}`;
  - `{"kind": "trace", "trace_id": str, "service": str|None, "claim": str}`;
  - `{"kind": "log", "service": str, "quote": str}`;
  - any other dict, or one missing required fields, becomes `{"kind": "text", "text": json.dumps(original)}`.

  Services are normalised like causes: lower case, with whitespace and underscores turned into hyphens. Normalisation never raises.
- **`evidence.check(report, snap)`** returns `{"items": [{"kind", "grounded": bool, "reason": str}...], "grounded": int, "total": int}`. An item is grounded when:
  - **metric:** the summary has a row for (service, signal), where `restarts` maps to the `uptime_s` series, and its score is ≥ 0.5;
  - **trace:** the trace id exists among the spans, and if a service is given, the trace has a span of that service;
  - **log:** the quote has at least 8 characters after trimming, and some log of that service contains it (case-insensitive, whitespace collapsed);
  - **text:** never grounded.
- **`evaluate.run`** adds `"evidence_check": evidence.check(report, snap)` to every record. `summarise` rows gain `grounded`: the scenario-balanced mean of `grounded/total` over records with `total > 0`, or None if there are none. `format_summary` adds a `grounded` column.
- **`heuristic.diagnose`** evidence becomes metric items: `{"kind": "metric", "service", "signal", "claim": "<before> -> <after>"}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_evidence.py`:
```python
from rootcause import evidence
from rootcause.score import Report, make_report

T0 = 900.0


def series(base, fault):
    return [[float(t), base] for t in range(0, 901, 15)] + [[float(t), fault] for t in range(915, 1215, 15)]


SNAP = {"meta": {"alert": "a", "baseline_start": 0.0, "fault_start": T0, "end": 1200.0},
        "metrics": {"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)}},
        "spans": [{"trace_id": "abc", "span_id": "s", "parent_id": "", "service": "payment", "name": "charge",
                   "start_ms": 910000.0, "dur_ms": 5.0, "error": True, "message": "", "attributes": {}, "events": []}],
        "logs": [{"ts": "1970-01-01T00:15:20Z", "service": "payment", "severity": "WARN", "severity_number": 13,
                  "body": "Payment request failed.   Invalid token.", "trace_id": "abc"}]}


def report(*items):
    return make_report({"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                        "evidence": list(items), "confidence": 0.5})


def test_normalisation_keeps_strings_and_never_raises():
    r = report("plain words", {"kind": "metric", "service": "Payment", "signal": "error_ratio", "claim": "up"},
               {"kind": "weird"}, {"kind": "log"}, 42, None)
    assert r.evidence[0] == "plain words"
    assert r.evidence[1] == {"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "up"}
    assert all(e["kind"] == "text" for e in r.evidence[2:4])


def test_each_kind_is_checked_against_the_snapshot():
    r = report({"kind": "metric", "service": "payment", "signal": "error_ratio", "claim": "0 -> 0.3"},
               {"kind": "metric", "service": "cart", "signal": "error_ratio", "claim": "flat"},
               {"kind": "trace", "trace_id": "abc", "service": "payment", "claim": "error span"},
               {"kind": "trace", "trace_id": "abc", "service": "cart", "claim": "wrong service"},
               {"kind": "trace", "trace_id": "zzz", "claim": "made up"},
               {"kind": "log", "service": "payment", "quote": "request failed. invalid TOKEN"},
               {"kind": "log", "service": "payment", "quote": "failed"},
               "free text")
    c = evidence.check(r, SNAP)
    assert [i["grounded"] for i in c["items"]] == [True, False, True, False, False, True, False, False]
    assert c["grounded"] == 3 and c["total"] == 8


def test_empty_evidence():
    assert evidence.check(Report("no_incident"), SNAP) == {"items": [], "grounded": 0, "total": 0}
```

Append to `tests/test_evaluate.py`:
```python
def test_records_store_the_evidence_check_and_summary_reports_grounded(lib):
    def solve(snap):
        return Report("incident", (Cause("payment", "errors"),), ("free text",), 0.5), {}

    evaluate.run("g", solve, out_dir=lib / "runs")
    rec = json.loads((lib / "runs" / "g" / "pay__0.json").read_text())
    assert rec["evidence_check"] == {"items": [{"kind": "text", "grounded": False, "reason": "free text is not checkable"}],
                                     "grounded": 0, "total": 1}
    rows = {r["category"]: r for r in evaluate.summarise("g", lib / "runs")}
    assert rows["easy"]["grounded"] == 0.0
```
In `tests/test_heuristic.py`, update the evidence assertion in `test_names_the_service_whose_fault_signal_rose_most`:
```python
    assert r.evidence[0]["kind"] == "metric" and r.evidence[0]["service"] == "payment" and r.evidence[0]["signal"] == "error_ratio"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evidence.py tests/test_evaluate.py tests/test_heuristic.py -q`
Expected: FAIL (`rootcause.evidence` is missing, evidence is coerced to strings, and there is no `evidence_check`).

- [ ] **Step 3: Implement**

In `rootcause/score.py`, replace the evidence normalisation in `make_report` (currently `evidence = tuple(str(e) for e in evidence)`) with:
```python
    evidence = tuple(_evidence_item(e) for e in evidence)
```
and add:
```python
_EVIDENCE_FIELDS = {"metric": ("service", "signal"), "trace": ("trace_id",), "log": ("service", "quote")}


def _service(s):
    return re.sub(r"[\s_]+", "-", s.strip().lower())


def _evidence_item(e):
    """Strings stay strings; dicts become a checkable item, or a text item if they aren't one. Never raises."""
    if isinstance(e, str):
        return e
    kind = e.get("kind") if isinstance(e, dict) else None
    need = _EVIDENCE_FIELDS.get(kind)
    if need is None or not all(isinstance(e.get(f), str) and e.get(f).strip() for f in need):
        return {"kind": "text", "text": json.dumps(e, default=str)}
    item = {"kind": kind, **{f: e[f].strip() for f in need}}
    if "service" in item:
        item["service"] = _service(item["service"])
    if kind == "trace":
        item["service"] = _service(e["service"]) if isinstance(e.get("service"), str) and e["service"].strip() else None
    if kind in ("metric", "trace"):
        item["claim"] = str(e.get("claim", ""))
    return item
```
If `make_report` already has a service-normalising helper (from the week-2 fix), reuse it instead of adding `_service`; don't keep two.

`rootcause/evidence.py`:
```python
"""Check that a report's cited evidence exists in the snapshot it was made from (spec section 9)."""
import re

from rootcause import summary


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _check(item, snap, rows):
    if isinstance(item, str) or item.get("kind") == "text":
        return False, "free text is not checkable"
    kind = item["kind"]
    if kind == "metric":
        row = rows.get((item["service"], item["signal"]))
        if row is None:
            return False, "no such series"
        return (row["score"] >= 0.5, "changed" if row["score"] >= 0.5 else "series did not change notably")
    if kind == "trace":
        spans = [s for s in snap["spans"] if s["trace_id"] == item["trace_id"]]
        if not spans:
            return False, "no such trace"
        if item.get("service") and all(s["service"] != item["service"] for s in spans):
            return False, "trace has no span of that service"
        return True, "trace found"
    if kind == "log":
        quote = _norm(item["quote"])
        if len(quote) < 8:
            return False, "quote too short to be specific"
        hit = any(lg["service"] == item["service"] and quote in _norm(lg["body"]) for lg in snap["logs"])
        return hit, "log line found" if hit else "no such log line"
    return False, "unknown kind"


def check(report, snap):
    rows = {(r["service"], r["signal"]): r for r in summary.changes(snap)} if report.evidence else {}
    items = []
    for item in report.evidence:
        ok, reason = _check(item, snap, rows)
        items.append({"kind": "text" if isinstance(item, str) else item["kind"], "grounded": ok, "reason": reason})
    return {"items": items, "grounded": sum(i["grounded"] for i in items), "total": len(items)}
```

In `rootcause/heuristic.py`, replace the evidence line:
```python
    evidence = tuple({"kind": "metric", "service": r["service"], "signal": r["signal"],
                      "claim": f"{r['baseline']:.3g} -> {r['value']:.3g}"} for r in rows[:3])
```

In `rootcause/evaluate.py`:
- Import `evidence`.
- In `run`, add `"evidence_check": evidence.check(report, snap)` to `rec`, after `"score"`.
- In `_row`, add `"grounded": rate(lambda r: None if not r.get("evidence_check", {}).get("total") else r["evidence_check"]["grounded"] / r["evidence_check"]["total"])`.
- In `format_summary`, add a `grounded` header and cell, `fmt(r["grounded"])`, before `errors`.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evidence.py tests/test_score.py tests/test_heuristic.py tests/test_evaluate.py -q`, then the full suite with `-W error`.
Expected: all pass. A score test asserting `evidence` as a tuple of strings still holds for string input.

- [ ] **Step 5: Commit**

```bash
git add rootcause/score.py rootcause/evidence.py rootcause/heuristic.py rootcause/evaluate.py tests/
git commit -m "Structured evidence and a checker that verifies cited metrics, traces and log lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Agent v1

**Files:**
- Modify: `rootcause/agent.py` (add `NAME_V1`, `SYSTEM_V1`), `rootcause/cli.py` (`SOLVERS["agent-v1"]`)
- Test: extend `tests/test_agent.py` and `tests/test_cli.py`

**Interfaces:**
- `agent.NAME_V1 = "agent-v1"`.
- `agent.SYSTEM_V1` is `SYSTEM` with the evidence line replaced, and with one sentence added saying to start with `top_changes` and `service_map`. It contains the same anti-anchoring and "nothing may be wrong" sentences as v0, so the only differences from v0 are the tools and the evidence format.
- CLI: `SOLVERS["agent-v1"]` gives `("agent-v1", Agent(models=MODELS[:1], attempts=5, toolset=tools_v1, system=SYSTEM_V1, name=NAME_V1).solve, (QuotaExhausted,))`. `eval agent-v1` and `summary agent-v1` work.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent.py`:
```python
def test_v1_prompt_keeps_v0_priors_and_asks_for_structured_evidence():
    for sentence in ("often NOT the cause", "It is possible that nothing is actually wrong"):
        assert sentence in agent.SYSTEM and sentence in agent.SYSTEM_V1
    assert '"kind": "metric"' in agent.SYSTEM_V1 and "top_changes" in agent.SYSTEM_V1
    assert agent.NAME_V1 == "agent-v1"
```
Append to `tests/test_cli.py`:
```python
def test_agent_v1_solver_uses_v1_tools_and_prompt(monkeypatch):
    from rootcause import agent, tools_v1
    built = {}

    class Fake:
        def __init__(self, **kw):
            built.update(kw)

        def solve(self, snap):
            raise AssertionError("not called")

    monkeypatch.setattr(agent, "Agent", Fake)
    name, _, stop_on = cli.SOLVERS["agent-v1"]()
    assert name == "agent-v1" and stop_on == (agent.QuotaExhausted,)
    assert built["toolset"] is tools_v1 and built["system"] == agent.SYSTEM_V1 and built["models"] == agent.MODELS[:1]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent.py tests/test_cli.py -q`
Expected: FAIL (`SYSTEM_V1` missing; `KeyError: 'agent-v1'`).

- [ ] **Step 3: Implement**

In `rootcause/agent.py`, after `SYSTEM`:
```python
NAME_V1 = "agent-v1"
SYSTEM_V1 = SYSTEM.replace(
    ' "evidence": ["<short facts you observed>"],\n',
    ' "evidence": [  // cite what you saw so it can be checked:\n'
    '   {"kind": "metric", "service": "<service>", "signal": "<signal>", "claim": "<before -> after>"},\n'
    '   {"kind": "trace", "trace_id": "<id>", "service": "<service>", "claim": "<what the trace shows>"},\n'
    '   {"kind": "log", "service": "<service>", "quote": "<exact text copied from a log line>"}],\n'
).replace("Use the tools to look at the telemetry, ",
          "Use the tools to look at the telemetry (start with top_changes and service_map), ")
assert SYSTEM_V1 != SYSTEM  # both replacements must have matched
```
Replace the `assert` with a `ValueError` if the codebase avoids module-level asserts. The point is that a silent no-op replacement must fail loudly.

In `rootcause/cli.py`, add:
```python
def _agent_v1_solver():
    from rootcause import agent, tools_v1
    a = agent.Agent(models=agent.MODELS[:1], attempts=5, toolset=tools_v1, system=agent.SYSTEM_V1, name=agent.NAME_V1)
    return agent.NAME_V1, a.solve, (agent.QuotaExhausted,)
```
and register it in `SOLVERS` as `"agent-v1": _agent_v1_solver`.

- [ ] **Step 4: Run tests**

Run the two files, then the full suite with `-W error`. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/agent.py rootcause/cli.py tests/test_agent.py tests/test_cli.py
git commit -m "Add agent v1: change-aware toolset and structured evidence, same priors as v0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: MCP tool server

**Files:**
- Create: `rootcause/mcp_server.py`
- Modify: `rootcause/cli.py` (`mcp <snapshot-dir>` command), `requirements.txt` (`mcp>=2.3`)
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- MCP SDK 2.3 low-level API, verified on this machine:
  - `Server(name, on_list_tools=..., on_call_tool=...)`;
  - the handlers are `async (ctx, params)` and return `types.ListToolsResult` / `types.CallToolResult`;
  - the client is `mcp.client.stdio.stdio_client(StdioServerParameters(command, args))` plus `ClientSession`;
  - the result has `content[0].text` and `is_error`.
- Produces:
  - `build_server(snap, toolset=tools_v1) -> Server`;
  - `serve(path, toolset=tools_v1)`, an async function that loads the snapshot with `snapshot.load` and runs over stdio;
  - `python -m rootcause.mcp_server <snapshot-dir>` as an entry point;
  - CLI `python -m rootcause mcp <snapshot-dir>`.
- Tool definitions come from `toolset.SCHEMAS`: `name`, `description`, and `parameters` passed as `inputSchema`. Every call returns `toolset.call(...)` text, with `is_error` set when that text starts with `{"error"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mcp_server.py`:
```python
import inspect
import json
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from rootcause import config, mcp_server, snapshot, tools_v1


def make_snapshot(d):
    d.mkdir(parents=True)
    pts = [[float(t), 0.0] for t in range(0, 901, 15)] + [[float(t), 0.3] for t in range(915, 1215, 15)]
    (d / "meta.json").write_text(json.dumps({"alert": "x", "baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}))
    (d / "metrics.json").write_text(json.dumps({"error_ratio": {"payment": pts}}))
    snapshot._write_jsonl_gz(d / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(d / "logs.jsonl.gz", [])
    (d / "truth.json").write_text(json.dumps({"causes": [{"accept": ["payment"], "fault_type": "errors"}]}))
    return d


async def session_calls(path, calls):
    params = StdioServerParameters(command=sys.executable, args=["-m", "rootcause.mcp_server", str(path)],
                                   cwd=str(config.ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            results = [await s.call_tool(n, a) for n, a in calls]
    return names, results


def test_mcp_output_equals_in_process_output(tmp_path):
    path = make_snapshot(tmp_path / "incident__x")
    calls = [("top_changes", {}), ("service_health", {"service": "payment"}), ("nope", {})]
    names, results = anyio.run(session_calls, path, calls)
    snap = snapshot.load(path)
    assert sorted(names) == sorted(tools_v1.TOOLS)
    for (n, a), res in zip(calls, results):
        assert res.content[0].text == tools_v1.call(snap, n, a)
    assert results[0].is_error is False and results[2].is_error is True


def test_server_never_reads_answer_files():
    src = inspect.getsource(mcp_server)
    assert "truth" not in src and "validation" not in src and "index.jsonl" not in src
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -q`
Expected: FAIL with `ModuleNotFoundError: rootcause.mcp_server`.

- [ ] **Step 3: Implement**

`rootcause/mcp_server.py`:
```python
"""MCP server: exposes a toolset over stdio for ONE recorded snapshot (read-only; only snapshot.load data).

Usage: python -m rootcause.mcp_server <snapshot-dir>   (or: python -m rootcause mcp <snapshot-dir>)"""
import sys
from pathlib import Path

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from rootcause import snapshot, tools_v1


def build_server(snap, toolset=tools_v1):
    async def on_list_tools(ctx, params):
        return types.ListToolsResult(tools=[
            types.Tool(name=s["function"]["name"], description=s["function"]["description"],
                       inputSchema=s["function"]["parameters"]) for s in toolset.SCHEMAS])

    async def on_call_tool(ctx, params):
        text = toolset.call(snap, params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    isError=text.startswith('{"error"'))

    return Server("rootcause", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve(path, toolset=tools_v1):
    server = build_server(snapshot.load(path), toolset)
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not (Path(argv[0]) / "meta.json").exists():
        print("usage: python -m rootcause.mcp_server <snapshot-dir>  (a directory containing meta.json)", file=sys.stderr)
        return 2
    anyio.run(serve, argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
If `isError=` is rejected by the installed SDK, use the field name its `CallToolResult` accepts (`is_error` is the attribute name) and say so in the report.

In `rootcause/cli.py`, add the parser `mc = sub.add_parser("mcp", help="serve the v1 tools for one snapshot over MCP (stdio)"); mc.add_argument("path")`. The dispatch is `elif args.cmd == "mcp": from rootcause import mcp_server; return mcp_server.main([args.path])`.

In `requirements.txt`, add the line `mcp>=2.3`.

Add one more test in `tests/test_mcp_server.py`, for a missing snapshot path:
```python
def test_bad_path_exits_with_usage(tmp_path, capsys):
    assert mcp_server.main([str(tmp_path / "nope")]) == 2
    assert "usage" in capsys.readouterr().err
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mcp_server.py -q`, then the full suite with `-W error`.
Expected: all pass. The stdio test takes a few seconds.

- [ ] **Step 5: Commit**

```bash
git add rootcause/mcp_server.py rootcause/cli.py requirements.txt tests/test_mcp_server.py
git commit -m "Add MCP tool server (stdio) for a recorded snapshot, with an in-process parity test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Live v1 runs and results (controller)

- [ ] **Step 1: Smoke on two tuning-set snapshots.** Run `python -m rootcause eval agent-v1 payment-failure-50 control-1` and read both transcripts in full. Check `find_leaks` on the transcript, that evidence items are structured, and the grounded rate.
- [ ] **Step 2: Batch.** Run `eval agent-v1 --runs 5` detached, the same way as v0. It is resumable on quota.
- [ ] **Step 3: Write `docs/results/week3.md`.**
  - Heuristic vs v0 vs v1 per category, from `summary <solver>`, for `--split tune` and `--split heldout`.
  - The grounded-evidence rate.
  - Tokens and requests per run.
  - Failure examples.
  - An honest statement of where v1 helps, where it doesn't, and that the held-out numbers are the ones to trust.
- [ ] **Step 4: Commit the results.**

**Week 3 is done when** the split is frozen, the v1 toolset is served both in-process and over MCP with a parity test, evidence is checked for every record, agent v1 has 5 runs on all 20 snapshots (spanning days if the quota requires it), and `docs/results/week3.md` compares all three solvers by split.

# Week 2: Scoring, Heuristic Baseline and Agent v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score diagnoses against ground truth with fixed rules, and build a heuristic baseline and a first Gemini tool-using agent (v0). Run both over the 20 recorded incident snapshots: once for the heuristic, 5 times each for the agent.

**Architecture:**
- **Solvers:** a solver is a function `solve(snap) -> (Report, info)` that sees only what `snapshot.load()` returns.
- **Runner:** `evaluate.run` loads each snapshot, calls the solver, and only then loads `truth.json` and scores with `score.score`. It writes one JSON record per (scenario, run), which makes it resumable.
- **Heuristic:** ranks services by how much a fault-indicating signal rose against the baseline window (`summary.changes`).
- **Agent v0:** a plain OpenAI-compatible tool loop against Gemini Flash-Lite over *naive* tools (raw series, trace and log search). The change-aware tools are week 3, so v0 vs v1 is the planned ablation.

**Tech Stack:** Python 3.11 (`.venv`), `openai` 1.x client against Gemini's OpenAI-compatible endpoint, `python-dotenv`, pytest. No new dependencies; reports are validated with dataclasses.

**Spec:** `docs/superpowers/specs/2026-09-25-rootcause-design.md` (sections 6, 8, 8b, 10). Week-1 data decisions are in `scenarios/NOTES.md`.

## Global Constraints

- Everything stays under `D:\rootcause`. `data/` is git-ignored. Run Python as `.venv/Scripts/python.exe` from `D:\rootcause`, using Git Bash on Windows.
- Cost ₹0: only the Gemini free tier, with models `gemini-3.5-flash-lite` then the fallback `gemini-flash-lite-latest`. The key is `GEMINI_API_KEY` in `D:\rootcause\.env`; **never print, log or commit it**.
- **Tool boundary:** solvers get only `snapshot.load(path)` (meta, metrics, spans, logs). `truth.json`, `validation.json`, `index.jsonl`, `scenarios/` and `NOTES.md` name the answer and must never reach a solver. The truth is loaded only after `solve` returns.
- **Scoring rules (spec 8b), verbatim:**
  - Single-cause incident: correct iff the top-ranked cause's service is in the scenario's `accept` list. Top-3 is also reported. Naming a noisy scenario's decoy first is wrong.
  - Two-fault incident: credit = the fraction of true causes matched by any listed cause (0, ½, 1).
  - Control: correct iff the verdict is `no_incident`; any `incident` verdict is a false alarm.
  - Fault type: correct iff the matched cause's `fault_type` equals the truth's.
  - `insufficient_evidence` is wrong in plain accuracy and is left out of the covered set in accuracy-vs-coverage.
- Verdicts are `incident` / `no_incident` / `insufficient_evidence`. Fault types are `errors` / `latency` / `resource`. At most 3 causes.
- The heuristic threshold is fixed a priori at **1.0**, meaning the signal at least doubled. It is never tuned to the results; a sweep may be *reported* but never used to pick the value.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Review Focus

1. **Malformed model answers.** Expected answers include: JSON wrapped in ``` fences or surrounded by prose, extra keys, more than 3 causes, an unknown fault type, a missing confidence, or a non-JSON reply. The parser must extract the JSON, truncate to 3 causes, and reject what can't be repaired. The agent asks once for a corrected answer, then records `insufficient_evidence` with the parse error. Tested in Tasks 1 and 6.
2. **Gemini failures.** A per-minute 429 retries with backoff. A per-day 429 falls back to the next model, then stops the batch cleanly (`QuotaExhausted`) so it can resume. 503s, timeouts and connection errors are retried and never silently skipped. Tested in Tasks 6 and 4.
3. **Missing data.** A service with no points in a window (a paused container, a series that starts mid-window) is skipped by `summary.changes` and never crashes the heuristic. Tested in Task 2.
4. **Bad tool arguments from the model.** Unknown tool, unknown service or signal, wrong types, malformed JSON arguments. Each returns an error naming the valid options instead of raising, and no tool output exceeds `MAX_TOOL_CHARS`. Tested in Task 5.
5. **Interrupted batches.** A crash or quota stop mid-run, then a re-run, must not duplicate or overwrite records. `summarise` counts only complete records and reports how many runs each scenario has. Tested in Task 4.

## File Structure

```
rootcause/score.py      Report/Cause dataclasses, make_report (validation), parse_report (LLM text), score (spec 8b)
rootcause/summary.py    changes(snap): per (service, signal) baseline vs fault-window comparison, ranked
rootcause/heuristic.py  diagnose(snap) -> Report; solve(snap) -> (Report, info)
rootcause/evaluate.py   targets, run (resumable, truth loaded after solve), summarise, format_summary
rootcause/tools.py      agent v0 tools over a loaded snapshot + OpenAI tool schemas + call()
rootcause/agent.py      Gemini tool loop: throttle, retry/fallback, QuotaExhausted, repair, transcript, usage
rootcause/cli.py        + `eval {heuristic,agent} [--runs N] [ids...]` and `summary {heuristic,agent}`
tests/test_score.py, test_summary.py, test_heuristic.py, test_evaluate.py, test_tools.py, test_agent.py
docs/results/week2.md   results write-up (Task 7)
```

---

### Task 1: Reports and scoring

**Files:**
- Create: `rootcause/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Produces: `Cause(service: str, fault_type: str)`, `Report(verdict: str, causes: tuple[Cause, ...] = (), evidence: tuple[str, ...] = (), confidence: float = 0.0)` (frozen dataclasses); `make_report(d: dict) -> Report` (raises `ValueError`); `parse_report(text: str) -> Report` (raises `ValueError`); `report_to_dict(r: Report) -> dict`; `score(report: Report, truth: dict) -> dict` with keys `correct` (float 0..1), `top3` (bool), `fault_type_ok` (bool or None for controls), `false_alarm` (bool), `abstained` (bool). Constants `VERDICTS`, `FAULT_TYPES`, `MAX_CAUSES = 3`.

- [ ] **Step 1: Write the failing tests**

`tests/test_score.py`:
```python
import pytest

from rootcause.score import Cause, Report, make_report, parse_report, report_to_dict, score

SINGLE = {"causes": [{"accept": ["payment"], "fault_type": "errors"}]}
TWO = {"causes": [{"accept": ["payment"], "fault_type": "errors"},
                  {"accept": ["recommendation"], "fault_type": "resource"}]}
CONTROL = {"causes": []}


def inc(*pairs, confidence=0.8):
    return Report("incident", tuple(Cause(s, f) for s, f in pairs), ("e",), confidence)


def test_make_report_validates_and_normalises():
    r = make_report({"verdict": "incident", "confidence": 0.7, "evidence": ["x"],
                     "causes": [{"service": " Payment ", "fault_type": "ERRORS"}]})
    assert r == Report("incident", (Cause("payment", "errors"),), ("x",), 0.7)


def test_make_report_truncates_to_three_causes_and_clamps_confidence():
    causes = [{"service": f"s{i}", "fault_type": "latency"} for i in range(5)]
    r = make_report({"verdict": "incident", "causes": causes, "confidence": 7})
    assert [c.service for c in r.causes] == ["s0", "s1", "s2"] and r.confidence == 1.0


@pytest.mark.parametrize("bad", [
    {"verdict": "maybe"},
    {"verdict": "incident", "causes": []},
    {"verdict": "incident", "causes": [{"service": "payment", "fault_type": "slow"}]},
    {"verdict": "incident", "causes": [{"service": "", "fault_type": "errors"}]},
    {"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}], "confidence": "high"},
    ["not", "a", "dict"],
])
def test_make_report_rejects_invalid(bad):
    with pytest.raises(ValueError):
        make_report(bad)


def test_non_incident_verdicts_drop_causes():
    r = make_report({"verdict": "no_incident", "causes": [{"service": "payment", "fault_type": "errors"}]})
    assert r.causes == () and r.verdict == "no_incident"


def test_parse_report_handles_fences_and_prose():
    text = 'Here is my answer:\n```json\n{"verdict": "no_incident", "confidence": 0.9}\n```\nThanks.'
    assert parse_report(text) == Report("no_incident", (), (), 0.9)


def test_parse_report_rejects_non_json():
    with pytest.raises(ValueError):
        parse_report("I think it is the payment service.")


def test_report_round_trips_through_dict():
    r = inc(("payment", "errors"))
    assert make_report(report_to_dict(r)) == r


def test_single_cause_scoring_uses_top_ranked_only():
    assert score(inc(("payment", "errors")), SINGLE)["correct"] == 1.0
    wrong_first = score(inc(("checkout", "errors"), ("payment", "errors")), SINGLE)
    assert wrong_first["correct"] == 0.0 and wrong_first["top3"] is True
    assert score(inc(("payment", "latency")), SINGLE)["fault_type_ok"] is False


def test_two_fault_partial_credit_and_distinct_matching():
    assert score(inc(("payment", "errors"), ("recommendation", "resource")), TWO)["correct"] == 1.0
    half = score(inc(("payment", "errors"), ("cart", "errors")), TWO)
    assert half["correct"] == 0.5 and half["fault_type_ok"] is False
    assert score(inc(("payment", "errors"), ("payment", "errors")), TWO)["correct"] == 0.5


def test_controls_and_false_alarms():
    ok = score(Report("no_incident"), CONTROL)
    assert ok["correct"] == 1.0 and ok["false_alarm"] is False and ok["fault_type_ok"] is None
    alarm = score(inc(("payment", "errors")), CONTROL)
    assert alarm["correct"] == 0.0 and alarm["false_alarm"] is True


def test_abstention_is_wrong_but_flagged():
    for truth in (SINGLE, CONTROL):
        s = score(Report("insufficient_evidence"), truth)
        assert s["correct"] == 0.0 and s["abstained"] is True and s["false_alarm"] is False


def test_no_incident_on_a_real_incident_is_wrong():
    s = score(Report("no_incident"), SINGLE)
    assert s["correct"] == 0.0 and s["top3"] is False and s["fault_type_ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'rootcause.score'`

- [ ] **Step 3: Implement `rootcause/score.py`**

```python
"""Diagnosis reports (validated) and the fixed scoring rules (spec section 8b)."""
import json
import re
from dataclasses import asdict, dataclass

VERDICTS = ("incident", "no_incident", "insufficient_evidence")
FAULT_TYPES = ("errors", "latency", "resource")
MAX_CAUSES = 3


@dataclass(frozen=True)
class Cause:
    service: str
    fault_type: str


@dataclass(frozen=True)
class Report:
    verdict: str
    causes: tuple = ()
    evidence: tuple = ()
    confidence: float = 0.0


def make_report(d):
    """Validate a dict (e.g. parsed model output) into a Report; raises ValueError naming the problem."""
    if not isinstance(d, dict):
        raise ValueError("report must be a JSON object")
    verdict = str(d.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {d.get('verdict')!r}")
    conf = d.get("confidence", 0.0)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise ValueError("confidence must be a number between 0 and 1")
    evidence = tuple(str(e) for e in (d.get("evidence") or []))
    causes = ()
    if verdict == "incident":
        raw = d.get("causes") or []
        if not isinstance(raw, list) or not raw:
            raise ValueError("an incident verdict needs at least one cause")
        out = []
        for c in raw[:MAX_CAUSES]:
            if not isinstance(c, dict):
                raise ValueError("each cause must be an object with service and fault_type")
            service = str(c.get("service", "")).strip().lower()
            fault_type = str(c.get("fault_type", "")).strip().lower()
            if not service:
                raise ValueError("cause service must be a non-empty string")
            if fault_type not in FAULT_TYPES:
                raise ValueError(f"fault_type must be one of {FAULT_TYPES}, got {c.get('fault_type')!r}")
            out.append(Cause(service, fault_type))
        causes = tuple(out)
    return Report(verdict, causes, evidence, float(min(1.0, max(0.0, conf))))


def parse_report(text):
    """Extract the JSON object from model text (fences/prose allowed) and validate it."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object found in the answer")
    try:
        d = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"answer is not valid JSON: {e}") from e
    return make_report(d)


def report_to_dict(r):
    return asdict(r)


def score(report, truth):
    """Spec 8b. truth = truth.json content ({"causes": [{"accept": [...], "fault_type": ...}, ...]})."""
    abstained = report.verdict == "insufficient_evidence"
    causes = truth["causes"]
    if not causes:  # control
        correct = 1.0 if report.verdict == "no_incident" else 0.0
        return {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None,
                "false_alarm": report.verdict == "incident", "abstained": abstained}
    if report.verdict != "incident":
        return {"correct": 0.0, "top3": False, "fault_type_ok": False, "false_alarm": False, "abstained": abstained}
    names = [c.service for c in report.causes]
    if len(causes) == 1:
        accept = set(causes[0]["accept"])
        correct = 1.0 if names[0] in accept else 0.0
        return {"correct": correct, "top3": any(n in accept for n in names),
                "fault_type_ok": bool(correct) and report.causes[0].fault_type == causes[0]["fault_type"],
                "false_alarm": False, "abstained": False}
    used, matched = set(), []
    for tc in causes:  # each reported cause may match at most one true cause
        hit = next((i for i, c in enumerate(report.causes) if i not in used and c.service in set(tc["accept"])), None)
        if hit is not None:
            used.add(hit)
        matched.append(hit)
    correct = sum(m is not None for m in matched) / len(causes)
    fault_ok = all(m is not None and report.causes[m].fault_type == tc["fault_type"] for m, tc in zip(matched, causes))
    return {"correct": correct, "top3": correct == 1.0, "fault_type_ok": fault_ok, "false_alarm": False,
            "abstained": False}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_score.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/score.py tests/test_score.py
git commit -m "Add diagnosis reports and the fixed scoring rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Change summary

**Files:**
- Create: `rootcause/summary.py`
- Test: `tests/test_summary.py`

**Interfaces:**
- Consumes: `signals.window_stat(points, start, end, stat)`, `signals.restarts(points, start, end)`, `signals.FLOORS`, and `config.RAMP_S`. The snapshot dict comes from `snapshot.load`: `meta` (`baseline_start`, `fault_start`, `end`) and `metrics` `{signal: {service: [[t, v], ...]}}`.
- Produces:
  - `windows(meta) -> ((b0, b1), (f0, f1))`, where the baseline is `(baseline_start, fault_start)` and the fault window is `(fault_start + RAMP_S, end)`.
  - `changes(snap) -> list[dict]` with keys `service, signal, baseline, value, score, direction ("up"|"down"), fault_type (str|None)`, sorted by score descending.
  - `score = |value - baseline| / max(|baseline|, FLOORS[signal])`. `mem_mb` uses the window max; the other signals use the mean. `uptime_s` becomes a `restarts` row.
  - `FAULT_TYPE_OF = {"error_ratio": "errors", "p95_ms": "latency", "mem_mb": "resource", "cpu_cores": "resource", "restarts": "resource", "rps": None}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_summary.py`:
```python
from rootcause import summary

META = {"baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}


def series(base, fault, step=15):
    pts = [[float(t), base] for t in range(0, 900, step)]
    return pts + [[float(t), fault] for t in range(900, 1215, step)]


def snap(metrics):
    return {"meta": META, "metrics": metrics, "spans": [], "logs": []}


def test_windows_skip_the_ramp():
    assert summary.windows(META) == ((0.0, 900.0), (960.0, 1200.0))


def test_changes_rank_relative_rise_with_floors():
    rows = summary.changes(snap({"error_ratio": {"payment": series(0.0, 0.3), "cart": series(0.0, 0.0)},
                                 "p95_ms": {"checkout": series(100.0, 150.0)}}))
    top = rows[0]
    assert (top["service"], top["signal"], top["direction"], top["fault_type"]) == ("payment", "error_ratio", "up", "errors")
    assert abs(top["score"] - 0.3 / 0.01) < 1e-9          # baseline 0 -> divided by the 0.01 floor
    checkout = next(r for r in rows if r["service"] == "checkout")
    assert abs(checkout["score"] - 0.5) < 1e-9


def test_memory_uses_the_window_peak():
    pts = series(60.0, 60.0)
    pts[-5][1] = 500.0  # one sawtooth peak inside the fault window
    row = next(r for r in summary.changes(snap({"mem_mb": {"recommendation": pts}})))
    assert row["value"] == 500.0 and row["fault_type"] == "resource"


def test_uptime_becomes_restarts():
    up = [[float(t), float(t)] for t in range(0, 1080, 15)] + [[1080.0, 5.0], [1095.0, 20.0]]
    row = summary.changes(snap({"uptime_s": {"email": up}}))[0]
    assert (row["signal"], row["value"], row["baseline"]) == ("restarts", 1, 0)


def test_services_without_data_in_a_window_are_skipped():
    late = [[float(t), 1.0] for t in range(960, 1215, 15)]  # no baseline points
    assert summary.changes(snap({"cpu_cores": {"ad": late}, "rps": {"cart": []}})) == []


def test_rps_rows_have_no_fault_type():
    row = summary.changes(snap({"rps": {"frontend": series(20.0, 40.0)}}))[0]
    assert row["fault_type"] is None and row["direction"] == "up"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_summary.py -q`
Expected: FAIL with `ImportError` / `ModuleNotFoundError` for `rootcause.summary`

- [ ] **Step 3: Implement `rootcause/summary.py`**

```python
"""Per-service change table over a snapshot: every signal's baseline window vs its fault window, ranked."""
from rootcause import config, signals

FAULT_TYPE_OF = {"error_ratio": "errors", "p95_ms": "latency", "mem_mb": "resource", "cpu_cores": "resource",
                 "restarts": "resource", "rps": None}
STAT = {"mem_mb": "max"}  # leaks show as a peak or sawtooth; every other signal uses the mean


def windows(meta):
    return (meta["baseline_start"], meta["fault_start"]), (meta["fault_start"] + config.RAMP_S, meta["end"])


def _row(service, signal, baseline, value):
    score = abs(value - baseline) / max(abs(baseline), signals.FLOORS[signal])
    return {"service": service, "signal": signal, "baseline": baseline, "value": value, "score": score,
            "direction": "up" if value >= baseline else "down", "fault_type": FAULT_TYPE_OF[signal]}


def changes(snap):
    base_w, fault_w = windows(snap["meta"])
    rows = []
    for signal, by_service in snap["metrics"].items():
        for service, pts in by_service.items():
            if signal == "uptime_s":
                value, base = signals.restarts(pts, *fault_w), signals.restarts(pts, *base_w)
                signal_name, base = "restarts", base if base is not None else (0 if value is not None else None)
            elif signal in FAULT_TYPE_OF:
                stat = STAT.get(signal, "mean")
                value, base = signals.window_stat(pts, *fault_w, stat), signals.window_stat(pts, *base_w, stat)
                signal_name = signal
            else:
                continue
            if value is None or base is None:
                continue
            rows.append(_row(service, signal_name, base, value))
    return sorted(rows, key=lambda r: (-r["score"], r["service"], r["signal"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_summary.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/summary.py tests/test_summary.py
git commit -m "Add per-service change summary (baseline vs fault window)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Heuristic baseline

**Files:**
- Create: `rootcause/heuristic.py`
- Test: `tests/test_heuristic.py`

**Interfaces:**
- Consumes: `summary.changes(snap)` (Task 2); `Report`, `Cause` (Task 1).
- Produces:
  - `THRESHOLD = 1.0`;
  - `RANKED = ("error_ratio", "p95_ms", "mem_mb", "cpu_cores", "restarts")`;
  - `diagnose(snap, threshold=THRESHOLD) -> Report`;
  - `solve(snap) -> (Report, {"solver": "heuristic"})`.
- `diagnose` behaviour:
  - Only rising rows of `RANKED` signals with `score >= threshold` count.
  - Causes are the first 3 distinct services, in score order.
  - The confidence is `s / (1 + s)` of the top score.
  - The evidence is the top 3 rows as text.
  - With no qualifying row, the verdict is `no_incident` with confidence 0.5.

- [ ] **Step 1: Write the failing tests**

`tests/test_heuristic.py`:
```python
from rootcause import heuristic
from rootcause.score import Cause

META = {"baseline_start": 0.0, "fault_start": 900.0, "end": 1200.0}


def series(base, fault):
    return [[float(t), base] for t in range(0, 900, 15)] + [[float(t), fault] for t in range(900, 1215, 15)]


def snap(metrics):
    return {"meta": META, "metrics": metrics, "spans": [], "logs": []}


def test_names_the_service_whose_fault_signal_rose_most():
    r = heuristic.diagnose(snap({"error_ratio": {"payment": series(0.0, 0.3), "checkout": series(0.0, 0.05)},
                                 "p95_ms": {"frontend": series(100.0, 130.0)}}))
    assert r.verdict == "incident"
    assert r.causes == (Cause("payment", "errors"), Cause("checkout", "errors"))
    assert 0.9 < r.confidence < 1.0 and "payment error_ratio" in r.evidence[0]


def test_traffic_and_falling_signals_are_ignored():
    r = heuristic.diagnose(snap({"rps": {"frontend": series(20.0, 80.0)},
                                 "p95_ms": {"cart": series(100.0, 10.0)}}))
    assert r.verdict == "no_incident" and r.causes == ()


def test_below_threshold_is_no_incident():
    r = heuristic.diagnose(snap({"cpu_cores": {"ad": series(0.10, 0.18)}}))  # +80% < doubled
    assert r.verdict == "no_incident" and r.confidence == 0.5


def test_at_most_three_distinct_services():
    m = {"error_ratio": {s: series(0.0, 0.1 * (i + 1)) for i, s in enumerate(["a", "b", "c", "d"])},
         "p95_ms": {"d": series(10.0, 1000.0)}}
    r = heuristic.diagnose(snap(m))
    assert [c.service for c in r.causes] == ["d", "c", "b"]


def test_solve_returns_report_and_info():
    report, info = heuristic.solve(snap({}))
    assert report.verdict == "no_incident" and info == {"solver": "heuristic"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_heuristic.py -q`
Expected: FAIL with `ImportError` for `rootcause.heuristic`

- [ ] **Step 3: Implement `rootcause/heuristic.py`**

```python
"""Baseline: name the service whose fault-indicating signal rose the most against its baseline window."""
from rootcause import summary
from rootcause.score import Cause, Report

THRESHOLD = 1.0  # the signal must at least double (score = relative rise); fixed a priori, never tuned to results
RANKED = ("error_ratio", "p95_ms", "mem_mb", "cpu_cores", "restarts")  # rps is load, not a fault signal


def diagnose(snap, threshold=THRESHOLD):
    rows = [r for r in summary.changes(snap)
            if r["signal"] in RANKED and r["direction"] == "up" and r["score"] >= threshold]
    if not rows:
        return Report("no_incident", (), (), 0.5)
    causes, seen = [], set()
    for r in rows:
        if r["service"] not in seen:
            seen.add(r["service"])
            causes.append(Cause(r["service"], r["fault_type"]))
        if len(causes) == 3:
            break
    evidence = tuple(f"{r['service']} {r['signal']} {r['baseline']:.3g} -> {r['value']:.3g}" for r in rows[:3])
    top = rows[0]["score"]
    return Report("incident", tuple(causes), evidence, top / (1 + top))


def solve(snap):
    return diagnose(snap), {"solver": "heuristic"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_heuristic.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/heuristic.py tests/test_heuristic.py
git commit -m "Add heuristic baseline: biggest rise of a fault signal, fixed doubling threshold

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Evaluation runner, summary and CLI

**Files:**
- Create: `rootcause/evaluate.py`
- Modify: `rootcause/cli.py`: add `eval` and `summary` subcommands
- Test: `tests/test_evaluate.py`; extend `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `scenarios.load_all()`, which returns `Scenario` with `.id` and `.category`;
  - `snapshot.latest_rows(index_path, ids)`, `snapshot.load(path)` and `snapshot.load_truth(path)`;
  - `score.score` and `score.report_to_dict`;
  - `heuristic.solve`.
- Produces:
  - `RUNS_DIR = config.DATA / "runs"`;
  - `targets(ids=None) -> list[(scenario_id, category, path)]`;
  - `run(solver_name, solve, runs=1, ids=None, out_dir=RUNS_DIR, stop_on=(), clock=time.time) -> {"completed": int, "stopped": str | None}`;
  - `summarise(solver_name, out_dir=RUNS_DIR) -> list[dict]`, one row per category plus `"all incidents"`;
  - `format_summary(rows) -> str` (a markdown table).
- Record file `out_dir/<solver>/<scenario>__<k>.json`: `{"scenario", "category", "run", "seconds", "report", "score", **info}`.
- `summarise` rows: `{"category", "scenarios", "runs", "accuracy_mean", "accuracy_std", "top3", "fault_type", "false_alarm", "abstain"}`.
  - Per run index k, accuracy is the mean of `correct` over that category's records. Mean and std are taken across the k values (population std; 0 for a single run).
  - The other rates are means over all records.
  - `fault_type` is computed over records whose `fault_type_ok` is not None.

- [ ] **Step 1: Write the failing tests**

`tests/test_evaluate.py`:
```python
import json

import pytest

from rootcause import config, evaluate, scenarios, snapshot
from rootcause.score import Cause, Report

from helpers import FIXTURES  # noqa: F401  (keeps tests/ on sys.path as elsewhere)


def make_snapshot(root, name, causes):
    d = root / name
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"alert": "x", "baseline_start": 0, "fault_start": 900, "end": 1200}))
    (d / "metrics.json").write_text("{}")
    snapshot._write_jsonl_gz(d / "spans.jsonl.gz", [])
    snapshot._write_jsonl_gz(d / "logs.jsonl.gz", [])
    (d / "truth.json").write_text(json.dumps({"causes": causes}))
    return d


@pytest.fixture
def lib(tmp_path, monkeypatch):
    snaps = tmp_path / "snapshots"
    a = make_snapshot(snaps, "incident__a", [{"accept": ["payment"], "fault_type": "errors"}])
    c = make_snapshot(snaps, "incident__c", [])
    (snaps / "index.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"scenario": "pay", "path": str(a), "valid": True},
        {"scenario": "ctl", "path": str(c), "valid": True},
        {"scenario": "gone", "path": str(c), "valid": True},   # no longer in the library: ignored
    ]))
    monkeypatch.setattr(config, "SNAPSHOTS", snaps)
    monkeypatch.setattr(scenarios, "load_all", lambda: [
        scenarios.Scenario("pay", "easy", "a", {}, {}, []), scenarios.Scenario("ctl", "control", "a", {}, {}, [])])
    return tmp_path


def test_targets_resolve_latest_rows_for_library_scenarios(lib):
    assert [(s, c) for s, c, _ in evaluate.targets()] == [("ctl", "control"), ("pay", "easy")]


def test_run_scores_after_solving_and_never_shows_truth(lib):
    seen = []

    def solve(snap):
        seen.append(set(snap))
        return Report("incident", (Cause("payment", "errors"),), (), 0.9), {"solver": "fake"}

    out = evaluate.run("fake", solve, runs=2, out_dir=lib / "runs")
    assert out == {"completed": 4, "stopped": None}
    assert all(keys == {"meta", "metrics", "spans", "logs"} for keys in seen)
    rec = json.loads((lib / "runs" / "fake" / "pay__1.json").read_text())
    assert rec["score"]["correct"] == 1.0 and rec["run"] == 1 and rec["category"] == "easy"
    ctl = json.loads((lib / "runs" / "fake" / "ctl__0.json").read_text())
    assert ctl["score"]["false_alarm"] is True


def test_run_is_resumable_and_stops_cleanly(lib):
    class Stop(Exception):
        pass

    calls = []

    def solve(snap):
        calls.append(1)
        if len(calls) == 2:
            raise Stop("quota")
        return Report("no_incident"), {}

    first = evaluate.run("s", solve, runs=1, out_dir=lib / "runs", stop_on=(Stop,))
    assert first["completed"] == 1 and "quota" in first["stopped"]
    second = evaluate.run("s", solve, runs=1, out_dir=lib / "runs", stop_on=(Stop,))
    assert second == {"completed": 1, "stopped": None}
    assert len(list((lib / "runs" / "s").glob("*.json"))) == 2


def test_unexpected_solver_errors_propagate(lib):
    def solve(snap):
        raise KeyError("bug")

    with pytest.raises(KeyError):
        evaluate.run("s", solve, out_dir=lib / "runs")


def test_summarise_means_and_spread_over_runs(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    recs = [("p1", "easy", 0, 1.0), ("p2", "easy", 0, 0.0), ("p1", "easy", 1, 1.0), ("p2", "easy", 1, 1.0),
            ("c1", "control", 0, 1.0), ("c1", "control", 1, 0.0)]
    for sid, cat, k, correct in recs:
        score = {"correct": correct, "top3": correct == 1.0, "fault_type_ok": None if cat == "control" else True,
                 "false_alarm": cat == "control" and correct == 0.0, "abstained": False}
        (d / f"{sid}__{k}.json").write_text(json.dumps({"scenario": sid, "category": cat, "run": k, "score": score}))
    rows = {r["category"]: r for r in evaluate.summarise("x", out_dir=tmp_path)}
    assert rows["easy"]["accuracy_mean"] == 0.75 and rows["easy"]["accuracy_std"] == 0.25
    assert rows["easy"]["scenarios"] == 2 and rows["easy"]["runs"] == 2
    assert rows["control"]["false_alarm"] == 0.5 and rows["control"]["fault_type"] is None
    assert rows["all incidents"]["accuracy_mean"] == 0.75
    assert "| easy |" in evaluate.format_summary(list(rows.values()))
```

Append to `tests/test_cli.py`:
```python
def test_eval_and_summary_commands_parse():
    p = cli.build_parser()
    a = p.parse_args(["eval", "heuristic"])
    assert (a.cmd, a.solver, a.runs, a.ids) == ("eval", "heuristic", 1, [])
    a = p.parse_args(["eval", "agent", "--runs", "5", "payment-failure-50"])
    assert (a.solver, a.runs, a.ids) == ("agent", 5, ["payment-failure-50"])
    assert p.parse_args(["summary", "heuristic"]).solver == "heuristic"


def test_eval_heuristic_runs_and_prints_summary(monkeypatch, capsys):
    from rootcause import evaluate
    calls = {}
    monkeypatch.setattr(evaluate, "run", lambda name, solve, runs, ids, stop_on=(): calls.update(name=name, runs=runs, ids=ids) or {"completed": 3, "stopped": None})
    monkeypatch.setattr(evaluate, "summarise", lambda name: [{"category": "easy"}])
    monkeypatch.setattr(evaluate, "format_summary", lambda rows: "TABLE")
    assert cli.main(["eval", "heuristic"]) == 0
    assert calls == {"name": "heuristic", "runs": 1, "ids": None}
    assert "TABLE" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluate.py tests/test_cli.py -q`
Expected: FAIL (`rootcause.evaluate` missing; `eval` is an invalid argparse choice)

- [ ] **Step 3: Implement `rootcause/evaluate.py`**

```python
"""Run a solver over the recorded snapshots (N runs each), score against truth, and summarise per category.

The solver only ever receives snapshot.load(path); truth.json is read after solve() returns."""
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path

from rootcause import config, scenarios, snapshot
from rootcause.score import report_to_dict, score

RUNS_DIR = config.DATA / "runs"


def targets(ids=None):
    lib = {s.id: s for s in scenarios.load_all()}
    rows = snapshot.latest_rows(Path(config.SNAPSHOTS) / "index.jsonl", ids or list(lib))
    return [(sid, lib[sid].category, rows[sid]["path"]) for sid in sorted(rows) if sid in lib]


def run(solver_name, solve, runs=1, ids=None, out_dir=RUNS_DIR, stop_on=(), clock=time.time):
    """Write out_dir/solver_name/<scenario>__<k>.json per run; existing records are kept (resumable)."""
    d = Path(out_dir) / solver_name
    d.mkdir(parents=True, exist_ok=True)
    done = 0
    for sid, category, path in targets(ids):
        for k in range(runs):
            f = d / f"{sid}__{k}.json"
            if f.exists():
                continue
            snap = snapshot.load(path)
            t0 = clock()
            try:
                report, info = solve(snap)
            except stop_on as e:  # e.g. the daily free-tier quota: stop cleanly, resume tomorrow
                return {"completed": done, "stopped": f"{type(e).__name__}: {e}"}
            rec = {"scenario": sid, "category": category, "run": k, "seconds": clock() - t0,
                   "report": report_to_dict(report), "score": score(report, snapshot.load_truth(path)), **info}
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            tmp.replace(f)  # a crash mid-write never leaves a half record that resume would skip
            done += 1
    return {"completed": done, "stopped": None}


def _row(category, recs):
    by_run = defaultdict(list)
    for r in recs:
        by_run[r["run"]].append(r["score"]["correct"])
    accs = [sum(v) / len(v) for v in by_run.values()]
    ft = [r["score"]["fault_type_ok"] for r in recs if r["score"]["fault_type_ok"] is not None]
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    return {"category": category, "scenarios": len({r["scenario"] for r in recs}), "runs": len(by_run),
            "accuracy_mean": mean(accs), "accuracy_std": statistics.pstdev(accs) if accs else None,
            "top3": mean([float(r["score"]["top3"]) for r in recs]),
            "fault_type": mean([float(x) for x in ft]),
            "false_alarm": mean([float(r["score"]["false_alarm"]) for r in recs]),
            "abstain": mean([float(r["score"]["abstained"]) for r in recs])}


ORDER = ["easy", "hard-cross-service", "hard-silent", "hard-noisy", "hard-two-faults", "control"]


def summarise(solver_name, out_dir=RUNS_DIR):
    recs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(out_dir) / solver_name).glob("*.json"))]
    by_cat = defaultdict(list)
    for r in recs:
        by_cat[r["category"]].append(r)
    rows = [_row(c, by_cat[c]) for c in sorted(by_cat, key=lambda c: ORDER.index(c) if c in ORDER else 99)]
    incidents = [r for r in recs if r["category"] != "control"]
    if incidents:
        rows.append(_row("all incidents", incidents))
    return rows


def format_summary(rows):
    fmt = lambda x: "-" if x is None else f"{x:.2f}"
    out = ["| category | scenarios | runs | accuracy (mean ± sd) | top-3 | fault type | false alarm | abstain |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['category']} | {r['scenarios']} | {r['runs']} | {fmt(r['accuracy_mean'])} ± "
                   f"{fmt(r['accuracy_std'])} | {fmt(r['top3'])} | {fmt(r['fault_type'])} | "
                   f"{fmt(r['false_alarm'])} | {fmt(r['abstain'])} |")
    return "\n".join(out)
```

- [ ] **Step 4: Wire the CLI**

In `rootcause/cli.py`, add `evaluate` and `heuristic` to the `from rootcause import ...` line. In `build_parser()`, after the `resanitize` parser:
```python
    ev = sub.add_parser("eval", help="run a solver over the recorded snapshots and score it")
    ev.add_argument("solver", choices=["heuristic", "agent"])
    ev.add_argument("--runs", type=int, default=1)
    ev.add_argument("ids", nargs="*")
    sm = sub.add_parser("summary", help="print the per-category score table for a solver's recorded runs")
    sm.add_argument("solver", choices=["heuristic", "agent"])
```
Add a function:
```python
def _eval(args):
    if args.solver == "heuristic":
        name, solve, stop_on = "heuristic", heuristic.solve, ()
    else:
        from rootcause import agent  # imported lazily: only the agent needs the Gemini client
        name, solve, stop_on = agent.NAME, agent.Agent().solve, (agent.QuotaExhausted,)
    out = evaluate.run(name, solve, runs=args.runs, ids=args.ids or None, stop_on=stop_on)
    print(f"{out['completed']} new runs" + (f"; stopped: {out['stopped']}" if out["stopped"] else ""))
    print(evaluate.format_summary(evaluate.summarise(name)))
    return 0 if not out["stopped"] else 4
```
In `_dispatch`, add:
```python
    elif args.cmd == "eval":
        return _eval(args)
    elif args.cmd == "summary":
        name = "heuristic" if args.solver == "heuristic" else "agent-v0"
        print(evaluate.format_summary(evaluate.summarise(name)))
```
(`agent.NAME` is `"agent-v0"` in Task 6; the summary command uses the same literal so it works before Task 6 exists.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluate.py tests/test_cli.py -q`, then the full suite with `-W error`.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add rootcause/evaluate.py rootcause/cli.py tests/test_evaluate.py tests/test_cli.py
git commit -m "Add resumable evaluation runner, per-category summary and eval/summary commands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Agent v0 tools (naive)

**Files:**
- Create: `rootcause/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: a snapshot dict from `snapshot.load` with these fields:
  - spans: `trace_id, span_id, parent_id, service, name, start_ms, dur_ms, error, message, attributes, events`;
  - logs: `ts (ISO-8601 Z), service, severity, severity_number, body, trace_id`;
  - metrics `{signal: {service: [[t, v]]}}`;
  - meta `fault_start`.
- Produces:
  - `MAX_TOOL_CHARS = 6000`;
  - `SIGNAL_NAMES = ("rps", "error_ratio", "p95_ms", "mem_mb", "cpu_cores", "uptime_s")`;
  - functions `list_services(snap)`, `get_metric(snap, service, signal)`, `search_traces(snap, service, errors_only=False, limit=10)`, `get_trace(snap, trace_id)` and `search_logs(snap, service, text="", min_severity=0, limit=20)`, each returning a JSON-serialisable dict;
  - `SCHEMAS` (OpenAI `tools=` list);
  - `call(snap, name, raw_args) -> str`, which never raises, returns JSON capped at `MAX_TOOL_CHARS` and accepts `raw_args` as a JSON string or dict.
- All times are seconds relative to the alert (`meta.fault_start`, which is t=0), rounded to whole seconds. Metric series are thinned to 1 point per minute. Values are rounded to 4 significant figures.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools.py`:
```python
import inspect
import json

from rootcause import tools

T0 = 1000.0
SNAP = {
    "meta": {"alert": "a", "baseline_start": T0 - 900, "fault_start": T0, "end": T0 + 300},
    "metrics": {"error_ratio": {"payment": [[T0 - 60 + 15 * i, 0.1234567 * i] for i in range(12)]},
                "mem_mb": {"kafka": [[T0, 600.0]]}},
    "spans": [
        {"trace_id": "t1", "span_id": "a", "parent_id": "", "service": "frontend", "name": "GET /cart",
         "start_ms": (T0 + 5) * 1000, "dur_ms": 900.0, "error": True, "message": "upstream failed",
         "attributes": {}, "events": []},
        {"trace_id": "t1", "span_id": "b", "parent_id": "a", "service": "payment", "name": "charge",
         "start_ms": (T0 + 6) * 1000, "dur_ms": 800.0, "error": True, "message": "Invalid token",
         "attributes": {}, "events": []},
        {"trace_id": "t2", "span_id": "c", "parent_id": "", "service": "payment", "name": "charge",
         "start_ms": (T0 - 100) * 1000, "dur_ms": 20.0, "error": False, "message": "",
         "attributes": {}, "events": []},
    ],
    "logs": [
        {"ts": "1970-01-01T00:16:50.000Z", "service": "payment", "severity": "ERROR", "severity_number": 17,
         "body": "Payment request failed. Invalid token.", "trace_id": "t1"},
        {"ts": "1970-01-01T00:15:00.5Z", "service": "payment", "severity": "INFO", "severity_number": 9,
         "body": "charged ok", "trace_id": "t2"},
    ],
}


def out(name, args):
    return json.loads(tools.call(SNAP, name, args))


def test_list_services_unions_metrics_spans_and_logs():
    assert out("list_services", {}) == {"services": ["frontend", "kafka", "payment"]}


def test_get_metric_thins_to_one_point_per_minute_relative_to_alert():
    r = out("get_metric", {"service": "payment", "signal": "error_ratio"})
    assert r["points"][0] == [-60, 0.0] and r["points"][1][0] == 0 and len(r["points"]) == 3
    assert r["points"][1][1] == 0.4938  # 4 significant figures


def test_unknown_names_return_valid_options():
    assert "payment" in out("get_metric", {"service": "nope", "signal": "error_ratio"})["valid_services"]
    assert "p95_ms" in out("get_metric", {"service": "payment", "signal": "nope"})["valid_signals"]
    assert "search_logs" in out("nope", {})["valid_tools"]


def test_search_traces_summarises_errors_and_slowest():
    r = out("search_traces", {"service": "payment", "errors_only": True})
    assert r["spans_found"] == 1 and r["slowest"][0]["trace_id"] == "t1"
    assert r["error_messages"] == {"Invalid token": 1}


def test_get_trace_orders_spans_by_start():
    r = out("get_trace", {"trace_id": "t1"})
    assert [s["service"] for s in r["spans"]] == ["frontend", "payment"] and r["spans"][0]["t"] == 5


def test_search_logs_filters_text_and_severity():
    r = out("search_logs", {"service": "payment", "text": "INVALID", "min_severity": 17})
    assert r["total"] == 1 and r["samples"][0]["t"] == 10 and "Invalid token" in r["samples"][0]["body"]


def test_bad_arguments_never_raise():
    assert "error" in out("get_metric", "{not json")
    assert "error" in out("search_traces", {"service": "payment", "limit": "many"})
    assert "error" in out("get_trace", {})


def test_outputs_are_capped():
    big = dict(SNAP, logs=[dict(SNAP["logs"][0], body="x" * 500) for _ in range(500)])
    text = tools.call(big, "search_logs", {"service": "payment", "limit": 500})
    assert len(text) <= tools.MAX_TOOL_CHARS


def test_schemas_cover_every_tool():
    assert {s["function"]["name"] for s in tools.SCHEMAS} == set(tools.TOOLS)


def test_tools_never_touch_answer_files():
    src = inspect.getsource(tools)
    assert "truth" not in src and "validation" not in src and "index.jsonl" not in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tools.py -q`
Expected: FAIL with `ModuleNotFoundError` for `rootcause.tools`

- [ ] **Step 3: Implement `rootcause/tools.py`**

```python
"""Agent v0 tools: naive, read-only views over one loaded snapshot (meta, metrics, spans, logs only).

Times are seconds relative to the alert (t=0 = meta.fault_start). v0 deliberately has no baseline
comparison or ranking; the change-aware tools come in week 3 (ablation: naive vs change-aware)."""
import json
from collections import Counter
from datetime import datetime, timezone

MAX_TOOL_CHARS = 6000
SIGNAL_NAMES = ("rps", "error_ratio", "p95_ms", "mem_mb", "cpu_cores", "uptime_s")


def _sig(x):
    return float(f"{x:.4g}") if isinstance(x, (int, float)) else x


def _epoch(ts):
    head, _, frac = ts.rstrip("Z").partition(".")
    return datetime.strptime(head, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() + float("0." + (frac or "0"))


def _services(snap):
    names = {s for series in snap["metrics"].values() for s in series}
    names |= {sp["service"] for sp in snap["spans"]} | {lg["service"] for lg in snap["logs"]}
    return sorted(names)


def list_services(snap):
    return {"services": _services(snap)}


def get_metric(snap, service, signal):
    if signal not in SIGNAL_NAMES:
        return {"error": f"unknown signal {signal!r}", "valid_signals": list(SIGNAL_NAMES)}
    series = snap["metrics"].get(signal, {})
    if service not in series:
        return {"error": f"no {signal} series for {service!r}", "valid_services": sorted(series)}
    t0, points, last_minute = snap["meta"]["fault_start"], [], None
    for t, v in series[service]:
        rel = round(t - t0)
        minute = rel // 60
        if minute != last_minute:  # thin to one point per minute
            points.append([rel, _sig(v)])
            last_minute = minute
    return {"service": service, "signal": signal, "points": points, "note": "t = seconds relative to the alert"}


def search_traces(snap, service, errors_only=False, limit=10):
    limit = int(limit)
    t0 = snap["meta"]["fault_start"]
    spans = [s for s in snap["spans"] if s["service"] == service and (s["error"] or not errors_only)]
    if not spans and service not in _services(snap):
        return {"error": f"unknown service {service!r}", "valid_services": _services(snap)}
    ops = Counter(s["name"] for s in spans)
    msgs = Counter(s["message"][:150] for s in spans if s["error"] and s["message"])
    slow = sorted(spans, key=lambda s: -s["dur_ms"])[:limit]
    return {"service": service, "spans_found": len(spans), "errors": sum(s["error"] for s in spans),
            "operations": dict(ops.most_common(limit)), "error_messages": dict(msgs.most_common(5)),
            "slowest": [{"trace_id": s["trace_id"], "name": s["name"], "dur_ms": _sig(s["dur_ms"]),
                         "t": round(s["start_ms"] / 1000 - t0), "error": s["error"]} for s in slow]}


def get_trace(snap, trace_id):
    t0 = snap["meta"]["fault_start"]
    spans = sorted((s for s in snap["spans"] if s["trace_id"] == trace_id), key=lambda s: s["start_ms"])
    if not spans:
        return {"error": f"no trace {trace_id!r} in this incident"}
    return {"trace_id": trace_id, "spans": [
        {"service": s["service"], "name": s["name"], "t": round(s["start_ms"] / 1000 - t0), "dur_ms": _sig(s["dur_ms"]),
         "error": s["error"], "message": s["message"][:200], "parent_id": s["parent_id"], "span_id": s["span_id"]}
        for s in spans[:40]], "total_spans": len(spans)}


def search_logs(snap, service, text="", min_severity=0, limit=20):
    limit, min_severity = int(limit), int(min_severity)
    t0, needle = snap["meta"]["fault_start"], str(text).lower()
    logs = [lg for lg in snap["logs"] if lg["service"] == service and needle in str(lg["body"]).lower()
            and (lg["severity_number"] or 0) >= min_severity]
    if not logs and service not in _services(snap):
        return {"error": f"unknown service {service!r}", "valid_services": _services(snap)}
    logs.sort(key=lambda lg: _epoch(lg["ts"]))
    return {"service": service, "total": len(logs), "samples": [
        {"t": round(_epoch(lg["ts"]) - t0), "severity": lg["severity"], "body": str(lg["body"])[:200],
         "trace_id": lg["trace_id"]} for lg in logs[-limit:]]}


TOOLS = {"list_services": list_services, "get_metric": get_metric, "search_traces": search_traces,
         "get_trace": get_trace, "search_logs": search_logs}

_STR = {"type": "string"}
SCHEMAS = [
    {"type": "function", "function": {"name": "list_services", "description": "List every service and infrastructure container with telemetry in this incident.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_metric", "description": "One metric series for one service, one point per minute, t = seconds relative to the alert (negative = before). Signals: rps, error_ratio, p95_ms, mem_mb, cpu_cores (cores), uptime_s (drops = restarts).",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "signal": {"type": "string", "enum": list(SIGNAL_NAMES)}}, "required": ["service", "signal"]}}},
    {"type": "function", "function": {"name": "search_traces", "description": "Summarise a service's spans: operations, error messages and the slowest spans (with trace ids).",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "errors_only": {"type": "boolean"}, "limit": {"type": "integer"}}, "required": ["service"]}}},
    {"type": "function", "function": {"name": "get_trace", "description": "All spans of one trace in start order: service, operation, duration, errors.",
                                      "parameters": {"type": "object", "properties": {"trace_id": _STR}, "required": ["trace_id"]}}},
    {"type": "function", "function": {"name": "search_logs", "description": "A service's log lines in time order, optionally filtered by case-insensitive text and minimum severity number (17 = ERROR).",
                                      "parameters": {"type": "object", "properties": {"service": _STR, "text": _STR, "min_severity": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["service"]}}},
]


def call(snap, name, raw_args):
    """Run one tool by name; never raises. Returns JSON text capped at MAX_TOOL_CHARS."""
    if name not in TOOLS:
        out = {"error": f"unknown tool {name!r}", "valid_tools": sorted(TOOLS)}
    else:
        try:
            args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args or {})
            out = TOOLS[name](snap, **args)
        except (TypeError, ValueError, KeyError) as e:
            out = {"error": f"bad arguments for {name}: {type(e).__name__}: {e}"}
    text = json.dumps(out)
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS - 40] + ' ..."}  [truncated: narrow the query]'
        text = text[:MAX_TOOL_CHARS]
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tools.py -q`
Expected: all pass. If `test_get_metric_thins...` disagrees on the 4-significant-figure value, check `0.1234567 * 4 = 0.4938268` → `0.4938`. The second kept point is `i = 4` (t = 0), because minute buckets are `rel // 60`: `-60 → -1`, `0..45 → 0`, `60.. → 1`. Fix the code, not the test, unless the arithmetic is wrong.

- [ ] **Step 5: Commit**

```bash
git add rootcause/tools.py tests/test_tools.py
git commit -m "Add agent v0 tools: naive metric, trace and log views over a loaded snapshot

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Agent v0 (Gemini tool loop)

**Files:**
- Create: `rootcause/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `tools.SCHEMAS`, `tools.call(snap, name, raw_args)` (Task 5); `score.parse_report`, `score.Report` (Task 1); `config.ROOT`.
- Produces:
  - constants: `NAME = "agent-v0"`, `MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]`, `MAX_STEPS = 15`, `MIN_INTERVAL_S = 4.5`;
  - `class QuotaExhausted(RuntimeError)`;
  - `make_client()`, which returns an OpenAI client from `.env`;
  - `class Agent(llm=None, models=MODELS, max_steps=MAX_STEPS, min_interval=MIN_INTERVAL_S, sleep=time.sleep, clock=time.monotonic)` with `.solve(snap) -> (Report, info)`. `info` holds `solver, models, steps, requests, prompt_tokens, completion_tokens, parse_error (str|None), transcript (list of {tool, args, output})`.
- Behaviour:
  - **Throttle:** at least `min_interval` seconds between requests.
  - **Per-minute 429** (message without "PerDay"/"per day"): sleep 15·2^attempt and retry, up to 3 attempts per model.
  - **Per-day 429:** mark that model exhausted and move to the next model. Raise `QuotaExhausted` when all models are exhausted.
  - **`InternalServerError` / `APITimeoutError` / `APIConnectionError`:** retry with the same backoff, then fall back to the next model. When every model has failed, re-raise the last error.
  - **Final answer:** parsed with `parse_report`. On `ValueError`, one repair turn without tools; if that still fails, the result is `Report("insufficient_evidence")` with `parse_error` set.
  - **Step limit:** a final no-tools turn asks for the JSON answer.

- [ ] **Step 1: Write the failing tests**

`tests/test_agent.py`:
```python
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from rootcause import agent
from rootcause.score import Cause, Report

SNAP = {"meta": {"alert": "Orders fail", "baseline_start": 0, "fault_start": 900, "end": 1200},
        "metrics": {"error_ratio": {"payment": [[900, 0.3]]}}, "spans": [], "logs": []}
FINAL = json.dumps({"verdict": "incident", "causes": [{"service": "payment", "fault_type": "errors"}],
                    "evidence": ["payment error_ratio 0.3"], "confidence": 0.8})


class Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, exclude_none=True):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [{"id": t.id, "type": "function",
                                "function": {"name": t.function.name, "arguments": t.function.arguments}}
                               for t in self.tool_calls]
        return {k: v for k, v in d.items() if v is not None}


def tool_call(name, args, i="c1"):
    return SimpleNamespace(id=i, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def resp(msg, p=100, c=10):
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=p, completion_tokens=c))


def rate_limit(text):
    return openai.RateLimitError(text, response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)


class FakeLLM:
    """Scripted responses; each item is a Msg (returned) or an Exception (raised). Records every request."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return resp(item)


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(script, **kw):
    llm, clock = FakeLLM(script), Clock()
    a = agent.Agent(llm=llm, sleep=clock.sleep, clock=clock.now, **kw)
    return a, llm, clock


def test_tool_call_then_final_answer():
    a, llm, _ = make([Msg(tool_calls=[tool_call("get_metric", {"service": "payment", "signal": "error_ratio"})]),
                      Msg(content=FINAL)])
    report, info = a.solve(SNAP)
    assert report == Report("incident", (Cause("payment", "errors"),), ("payment error_ratio 0.3",), 0.8)
    assert info["steps"] == 1 and info["requests"] == 2 and info["prompt_tokens"] == 200
    assert info["transcript"][0]["tool"] == "get_metric" and '"points"' in info["transcript"][0]["output"]
    assert "Orders fail" in llm.requests[0]["messages"][1]["content"]
    assert llm.requests[1]["messages"][-1]["role"] == "tool"


def test_invalid_answer_gets_one_repair_turn():
    a, llm, _ = make([Msg(content="it's payment"), Msg(content=FINAL)])
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and info["parse_error"] is None
    assert "tools" not in llm.requests[1]


def test_unrepairable_answer_becomes_insufficient_evidence():
    a, _, _ = make([Msg(content="no idea"), Msg(content="still prose")])
    report, info = a.solve(SNAP)
    assert report == Report("insufficient_evidence") and "no JSON" in info["parse_error"]


def test_step_limit_forces_a_final_answer():
    calls = [Msg(tool_calls=[tool_call("list_services", {}, i=str(i))]) for i in range(2)]
    a, llm, _ = make(calls + [Msg(content=FINAL)], max_steps=2)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and info["steps"] == 2 and "tools" not in llm.requests[-1]


def test_throttle_spaces_requests():
    a, _, clock = make([Msg(tool_calls=[tool_call("list_services", {})]), Msg(content=FINAL)], min_interval=4.5)
    a.solve(SNAP)
    assert clock.sleeps == [4.5]


def test_per_minute_rate_limit_backs_off_and_retries():
    a, _, clock = make([rate_limit("Resource exhausted. Please retry."), Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and 15 in clock.sleeps


def test_daily_quota_falls_back_then_raises():
    a, llm, _ = make([rate_limit("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                      Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert llm.requests[1]["model"] == agent.MODELS[1] and info["models"] == [agent.MODELS[1]]
    b, _, _ = make([rate_limit("PerDay quota"), rate_limit("PerDay quota")], min_interval=0)
    with pytest.raises(agent.QuotaExhausted):
        b.solve(SNAP)


def test_server_errors_retry_then_fall_back():
    err = openai.InternalServerError("overloaded", response=httpx.Response(503, request=httpx.Request("POST", "http://x")), body=None)
    a, llm, _ = make([err, err, err, Msg(content=FINAL)], min_interval=0)
    report, _ = a.solve(SNAP)
    assert report.verdict == "incident" and llm.requests[-1]["model"] == agent.MODELS[1]


def test_bad_tool_arguments_are_reported_to_the_model_not_raised():
    bad = SimpleNamespace(id="c1", function=SimpleNamespace(name="get_metric", arguments="{oops"))
    a, llm, _ = make([Msg(tool_calls=[bad]), Msg(content=FINAL)], min_interval=0)
    report, info = a.solve(SNAP)
    assert report.verdict == "incident" and "error" in info["transcript"][0]["output"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`
Expected: FAIL with `ModuleNotFoundError` for `rootcause.agent`

- [ ] **Step 3: Implement `rootcause/agent.py`**

```python
"""Agent v0: a plain Gemini (OpenAI-compatible) tool loop over one snapshot.

Returns a validated Report plus transcript and token usage. Free tier only: requests are spaced out, per-minute
rate limits back off, a per-day quota falls back to the next model and finally raises QuotaExhausted so a batch
can stop cleanly and resume later."""
import os
import time

from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

from rootcause import config, tools
from rootcause.score import Report, parse_report

NAME = "agent-v0"
MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
MAX_STEPS = 15
MIN_INTERVAL_S = 4.5  # stay under ~15 requests/minute on the free tier
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

SYSTEM = (
    "You are an SRE investigating an alert in a microservice web shop. Use the tools to look at the telemetry, "
    "then decide what is wrong. The alert describes a user-visible symptom; the service it mentions is often NOT "
    "the cause, so follow errors and latency to where they originate. Compare the period before the alert "
    "(negative t) with after it; prefer signals that changed over values that were always high. It is possible "
    "that nothing is actually wrong. When you are done, reply with ONLY a JSON object:\n"
    '{"verdict": "incident" | "no_incident" | "insufficient_evidence",\n'
    ' "causes": [{"service": "<service name>", "fault_type": "errors" | "latency" | "resource"}],  // up to 3, most likely first; empty unless incident\n'
    ' "evidence": ["<short facts you observed>"],\n'
    ' "confidence": <0..1>}'
)


class QuotaExhausted(RuntimeError):
    """Every model's daily free-tier quota is used up."""


def make_client():
    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    return OpenAI(base_url=BASE_URL, api_key=os.getenv("GEMINI_API_KEY"), timeout=90)


def _per_day(err):
    text = str(err).lower()
    return "perday" in text or "per day" in text


class Agent:
    def __init__(self, llm=None, models=MODELS, max_steps=MAX_STEPS, min_interval=MIN_INTERVAL_S,
                 sleep=time.sleep, clock=time.monotonic):
        self.llm, self.models, self.max_steps = llm, list(models), max_steps
        self.min_interval, self.sleep, self.clock = min_interval, sleep, clock
        self.exhausted, self._last = set(), None

    def _throttle(self):
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()

    def _chat(self, info, **kw):
        if self.llm is None:
            self.llm = make_client()
        last = None
        for model in self.models:
            if model in self.exhausted:
                continue
            for attempt in range(3):
                self._throttle()
                try:
                    r = self.llm.chat.completions.create(model=model, **kw)
                except RateLimitError as e:
                    last = e
                    if _per_day(e):
                        self.exhausted.add(model)
                        break
                    self.sleep(15 * 2 ** attempt)
                    continue
                except (InternalServerError, APITimeoutError, APIConnectionError) as e:
                    last = e
                    self.sleep(15 * 2 ** attempt)
                    continue
                info["requests"] += 1
                info["prompt_tokens"] += getattr(r.usage, "prompt_tokens", 0) or 0
                info["completion_tokens"] += getattr(r.usage, "completion_tokens", 0) or 0
                if model not in info["models"]:
                    info["models"].append(model)
                return r.choices[0].message
        if all(m in self.exhausted for m in self.models):
            raise QuotaExhausted(f"daily free-tier quota used up for {self.models}")
        raise last

    def _final(self, msgs, info, text):
        """Parse the answer; one repair turn without tools; otherwise insufficient_evidence."""
        try:
            return parse_report(text)
        except ValueError as e:
            msgs.append({"role": "user", "content": f"That answer was not valid ({e}). Reply with ONLY the JSON object."})
            m = self._chat(info, messages=msgs, temperature=0)
            msgs.append(m.model_dump(exclude_none=True))
            try:
                return parse_report(m.content or "")
            except ValueError as e2:
                info["parse_error"] = str(e2)
                return Report("insufficient_evidence")

    def solve(self, snap):
        info = {"solver": NAME, "models": [], "steps": 0, "requests": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "parse_error": None, "transcript": []}
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"ALERT (fired at t=0): {snap['meta']['alert']}"}]
        for _ in range(self.max_steps):
            m = self._chat(info, messages=msgs, tools=tools.SCHEMAS, temperature=0)
            msgs.append(m.model_dump(exclude_none=True))
            if not m.tool_calls:
                return self._final(msgs, info, m.content or ""), info
            for tc in m.tool_calls:
                out = tools.call(snap, tc.function.name, tc.function.arguments)
                info["steps"] += 1
                info["transcript"].append({"tool": tc.function.name, "args": tc.function.arguments, "output": out})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        msgs.append({"role": "user", "content": "Step limit reached. Give your final answer now as ONLY the JSON object."})
        m = self._chat(info, messages=msgs, temperature=0)
        msgs.append(m.model_dump(exclude_none=True))
        return self._final(msgs, info, m.content or ""), info
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_agent.py -q`, then the full suite with `-W error`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add rootcause/agent.py tests/test_agent.py
git commit -m "Add agent v0: Gemini tool loop with throttle, retry/fallback, quota stop and answer repair

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Live runs and results write-up (controller)

**Files:**
- Create: `docs/results/week2.md`
- Data: `data/runs/heuristic/*.json`, `data/runs/agent-v0/*.json` (git-ignored)

- [ ] **Step 1: Heuristic on all 20 snapshots**

Run: `.venv/Scripts/python.exe -m rootcause eval heuristic`
Expected: 20 new runs and a summary table. Open every record. Check that the score matches the truth by eye: the top service against the scenario's `accept` list, and controls' verdicts. Note each failure and *why* it failed, for example a decoy flood, a cross-service symptom, or a noisy control service.

- [ ] **Step 2: Agent smoke test (2 snapshots, 1 run each)**

Run: `.venv/Scripts/python.exe -m rootcause eval agent payment-failure-50 control-1`
Read both transcripts in full:
- Tool outputs must contain no flag vocabulary. Run `sanitize.find_leaks` over the transcript text, which must return nothing.
- Requests and tokens should be plausible.
- The report must parse.

Fix any harness bug with a test before going on.

- [ ] **Step 3: Agent batch (5 runs × 20, resumable)**

Run it detached; it takes about 1–2 hours and may stop on the daily quota:
```bash
.venv/Scripts/python.exe -u -c "import sys; sys.path.insert(0, '.'); from rootcause.cli import main; sys.exit(main(['eval', 'agent', '--runs', '5']))" > data/agent_eval.log 2>&1
```
If it stops with `QuotaExhausted` (exit 4), re-run the same command after the quota resets; finished runs are kept.

- [ ] **Step 4: Write `docs/results/week2.md`**

The write-up contains:
- both summary tables (`python -m rootcause summary heuristic` and `summary agent`);
- for each category, where each solver fails and one concrete transcript excerpt per failure mode;
- requests and tokens per run (mean, max);
- the free-tier limits actually hit;
- how many scenarios have all 5 agent runs.

Do not hide failures. If the agent loses to the heuristic, say so.

- [ ] **Step 5: Commit**

```bash
git add docs/results/week2.md
git commit -m "Week 2 results: heuristic vs agent v0 on 20 incidents

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Week 2 is done when** the heuristic has been scored on all 20 snapshots, agent v0 has 5 scored runs on each of the 20 (spanning days if the quota requires it), the full suite passes, and `docs/results/week2.md` reports both honestly.

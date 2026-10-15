# What helps the agent: model, tools, alert, prompt

**Status: 2026-10-15.** All four Nemotron batches are complete (5 runs on each of 20 incidents). The Gemini batches are partial: agent v0 has 32 of 100 runs and agent v1 64 of 100. Their numbers are marked, and they will change. Every figure below comes from [`report.md`](report.md), which also has the per-scenario tables.

## In short

- **The model matters most.** With the same tools and prompt, Nemotron 3 Super beats Gemini 3.5 Flash-Lite on fault incidents by 0.28 (95% interval +0.12 to +0.45).
- **No agent is clearly better than the simple rule.** The best agent beats the heuristic by about 0.08-0.10 on fault incidents, but the intervals include 0. It also raises more false alarms on the no-fault controls.
- **The change-aware tools do not change accuracy; they change where it comes from.** On Nemotron, v1's tools score the same as v0's naive tools (-0.02). They gain on silent faults, two-fault incidents and controls, and they lose on cross-service incidents. They also make the evidence checkable.
- **Reading the alert helps.** Replacing each incident's alert with one generic sentence lowers accuracy by 0.12 (interval -0.25 to -0.01) and doubles false alarms.
- **The two "prior" sentences in the prompt do nothing measurable** (-0.01, interval -0.07 to +0.06).
- **One run is not enough, and stated confidence overstates accuracy.** At temperature 0, all five runs of Nemotron v1 give the same top answer on only 8 of 20 incidents. Every agent states more confidence than it earns, Gemini the most (0.91 stated vs 0.54 right).

## The numbers

Accuracy on the 16 fault incidents, and the share of control runs answered correctly ("no incident"):

| solver | model | tools | fault incidents | controls | runs |
|---|---|---|---|---|---|
| heuristic | none | change ranking | 0.59 | 0.75 | 1 per incident |
| agent v0 | Gemini 3.5 Flash-Lite | naive | 0.41 | 1.00 | 32/100 (partial) |
| agent v1 | Gemini 3.5 Flash-Lite | change-aware | 0.40 | 1.00 | 64/100 (partial) |
| agent v0 | Nemotron 3 Super | naive | 0.69 | 0.30 | 100/100 |
| agent v1 | Nemotron 3 Super | change-aware | 0.68 | 0.50 | 100/100 |
| agent v1, no priors | Nemotron 3 Super | change-aware | 0.67 | 0.50 | 100/100 |
| agent v1, vague alert | Nemotron 3 Super | change-aware | 0.56 | 0.25 | 100/100 |

The paired comparisons compare each solver's mean score per incident with another's on the same 16 incidents. The interval is a 95% bootstrap over incidents. With 16 incidents an interval that includes 0 means the benchmark cannot tell the two apart.

| comparison | wins / ties / losses | mean difference | 95% interval |
|---|---|---|---|
| Nemotron v1 vs Gemini v1 (model) | 10 / 4 / 2 | +0.28 | +0.12 to +0.45 |
| Nemotron v1 vs heuristic | 5 / 8 / 3 | +0.08 | -0.05 to +0.23 |
| Nemotron v0 vs heuristic | 6 / 4 / 6 | +0.10 | -0.15 to +0.35 |
| Nemotron v1 vs Nemotron v0 (tools) | 6 / 4 / 6 | -0.02 | -0.14 to +0.11 |
| Nemotron v1, vague alert vs Nemotron v1 | 1 / 9 / 6 | -0.12 | -0.25 to -0.01 |
| Nemotron v1, no priors vs Nemotron v1 | 4 / 8 / 4 | -0.01 | -0.07 to +0.06 |
| Gemini v1 vs heuristic (partial) | 3 / 7 / 6 | -0.20 | -0.42 to -0.00 |

## Findings

### 1. The model, not the toolset, separates the agents

Gemini 3.5 Flash-Lite and Nemotron 3 Super get the same prompt, tools and step limit, yet the gap on fault incidents is +0.28. Most of it comes from what each model does when it runs out of steps. An agent still calling tools after 15 model turns is told to answer:

| solver | fault runs | hit the limit | then said "no incident" | accuracy when hit | accuracy otherwise |
|---|---|---|---|---|---|
| Gemini v1 (partial) | 51 | 32 (63%) | 19 of 32 | 0.28 | 0.63 |
| Nemotron v1 | 80 | 57 (71%) | 2 of 57 | 0.61 | 0.83 |

When Gemini Flash-Lite is cut off, it usually concludes that nothing is wrong. That happens even when its first tool call ranked the fault first. On ad-high-cpu, `top_changes` put ad's CPU at the top (+163x), and both of the first two v1 runs still answered "no incident" at 0.9 confidence. Nemotron names its best suspect. Gemini's perfect control score is the other side of the same habit, not better judgement. When it finishes on its own, its accuracy (0.63) is close to Nemotron's.

### 2. The change-aware tools move accuracy around

On Nemotron the overall score is the same with v0's naive tools (raw metric series, trace and log search) and v1's change-aware ones (`top_changes`, `service_health`, `service_map`), but the categories differ:

| category | Nemotron v0 (naive) | Nemotron v1 (change-aware) |
|---|---|---|
| cross-service (3 incidents) | 0.67 | 0.33 |
| silent (6) | 0.63 | 0.80 |
| two-fault (2) | 0.45 | 0.60 |
| controls (4), answered correctly | 0.30 | 0.50 |

- **Fewer false alarms.**
  - Nemotron v0 raised an incident on 60% of control runs, v1 on 35%.
  - Excluding control-2, where a real, unprompted payment latency spike happened during the no-fault window (see below), the counts are 7 of 15 for v0 and 2 of 15 for v1.
- **Checkable evidence.**
  - v1 cites structured evidence: a metric series, a trace id or a log line.
  - 98% of it exists in the snapshot (grounded), and 89% points at something anomalous (distinctive).
  - v0's free-text evidence cannot be checked.
- **Worse on cross-service incidents.**
  - With v1, the agent usually does see the real cause.
  - On valkey-cart-paused, the paused dependency appears in the trace text it read in 4 of 5 runs.
  - Yet in 2 of those 4 it still ranked the symptom service (cart) first.
  - A plausible reason is that `top_changes` lists the symptom's own spike first (cart p95 latency x1,850); this was not tested directly.
- **More tokens.** A v1 run sends 94k prompt tokens on average, against 74k for v0.

With 3 cross-service incidents, the 0.67 against 0.33 is 10 against 5 correct runs out of 15. That is the direction of an effect, not a measured size.

### 3. The alert carries real information

The vague-alert ablation gives every incident the same alert: "Users report that something is wrong with the shop." Against Nemotron v1, accuracy on fault incidents falls from 0.68 to 0.56. Correct control runs fall from 0.50 to 0.25, so false alarms double from 35% to 70%. Part of any agent's edge over the heuristic, which never reads the alert, is reading it. Several alerts name the functional area of the cause; `scenarios/NOTES.md` lists them.

### 4. The prompt's two priors do not matter

v1's prompt contains two sentences: "the service the alert mentions is often NOT the cause" and "it is possible that nothing is actually wrong". Removing them changes nothing measurable on Nemotron: -0.01 on fault incidents, the same 0.50 on controls, and 4 wins and 4 losses.

### 5. Runs are not repeatable, and confidence is inflated

Temperature 0 does not make a hosted model deterministic:

| solver | incidents where all runs agree | pairwise agreement | mean confidence | accuracy | calibration error (ECE) |
|---|---|---|---|---|---|
| Gemini v1 (partial) | 12 of 20 | 0.79 | 0.91 | 0.54 | 0.37 |
| Nemotron v0 | 6 of 20 | 0.54 | 0.82 | 0.61 | 0.20 |
| Nemotron v1 | 8 of 20 | 0.66 | 0.87 | 0.64 | 0.23 |
| Nemotron v1, vague alert | 9 of 20 | 0.58 | 0.85 | 0.49 | 0.36 |

(Accuracy and confidence here are over every run, controls included. ECE is over 5 equal-width confidence bins.)

- **A single run would be misleading.** On 12 of 20 incidents, Nemotron v1's five runs disagree on the top answer. This is why every batch is planned at 5 runs and the report averages per incident before comparing.
- **Gemini is more repeatable but more wrong.** Its runs agree more often (0.79). The agreement includes its repeated "no incident" answers (see finding 1).
- **Every agent is overconfident.** Stated confidence is 0.2-0.4 above accuracy. The vague alert makes this worse: accuracy drops but confidence barely moves. Confidence alone is not a usable signal for when to trust an answer; the coverage curve in `report.md` shows the same.

## Caveats

- **Controls are noisy.** control-2 contains a real latency spike (payment p95 8 ms → 7.5 s) in a window with no injected fault. The scoring rules, fixed in advance, count any incident answer on a control as wrong. Every agent that calls an incident there (all five Nemotron runs, and the heuristic) is marked down, although the spike is real.
- **Sixteen fault incidents, one demo app.** Category numbers rest on 2-6 incidents each.
- **Held out.** One held-out incident's v1 tool output was viewed during development; see the Provenance section of `report.md`.
- **Temperature 0.** The 5-run spread measures nondeterminism in the model APIs, not sampling.
- **Partial Gemini batches.** Gemini v0 and v1 are partial, and their ablations have not run yet. This page will be updated when they finish.

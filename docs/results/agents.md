# What helps the agent: model, tools, alert, prompt

**Status: 2026-10-20.** Complete: agents v0 and v1 on Gemini 3.5 Flash-Lite, Nemotron 3 Super and Nemotron 3.5 Super, and agent v1 on GLM 5.3 Flash (5 runs on each of 20 incidents); the no-priors, vague-alert and 30-step ablations on Nemotron 3 Super; the vague-alert ablation on Gemini (3 runs each). Running: the Gemini no-priors ablation (quota-bound); no conclusions are drawn from it here. Every figure below comes from [`report.md`](report.md), which marks running batches as partial and also has the per-scenario tables.

## In short

- **No agent is clearly better than the simple rule, on four models.** The best agents, v1 on Nemotron 3.5 Super and on GLM 5.3 Flash, score 0.14 above the heuristic on fault incidents, but every interval includes 0 (Nemotron 3.5's only just: -0.02 to +0.33), so this benchmark cannot tell them apart. Most of them also raise more false alarms on the no-fault controls.
- **The model matters most on fault incidents.** With the same agent, tools and prompt, GLM 5.3 Flash scores 0.32 above Gemini 3.5 Flash-Lite (95% interval +0.09 to +0.56) and Nemotron 3 Super 0.26 above it (+0.10 to +0.44). Agent v0 shows the same Nemotron gap (+0.23, interval +0.04 to +0.41).
- **A newer version of the same model does not measurably help.** Nemotron 3.5 Super against Nemotron 3 Super: +0.06 with agent v1 (interval -0.01 to +0.12) and +0.04 with v0 (-0.05 to +0.12).
- **Counting the controls shrinks the model gaps.** Over all 20 incidents, the 4 no-fault controls included, Nemotron v1 vs Gemini v1 falls to +0.11 (interval -0.09 to +0.31), because Nemotron raises far more false alarms (35% of control runs against Gemini's 0%). GLM vs Gemini stays only just positive (+0.21, interval +0.00 to +0.43).
- **The change-aware tools do not change accuracy; they change where it comes from.** v1's tools score the same as v0's naive tools on all three models that ran both (Nemotron -0.02, Gemini -0.06, Nemotron 3.5 -0.00; every interval includes 0). On Nemotron they score higher on silent faults, two-fault incidents and controls and lower on cross-service incidents (2-6 incidents per category, no intervals); on Gemini the categories barely move. They also make the evidence checkable.
- **Reading the alert helps, on both models tested.** Replacing each incident's alert with one generic sentence lowers fault accuracy by 0.12 on Nemotron and 0.13 on Gemini (intervals -0.25 to -0.01 and -0.27 to -0.01; permutation p = 0.09 and 0.07, so each alone is borderline) and raises false alarms on the controls (Nemotron 35% to 70%, Gemini 0% to 25%). Counting the controls, both drops clear zero: -0.15 (interval -0.26 to -0.05) and -0.16 (-0.29 to -0.03).
- **The two "prior" sentences in the prompt do nothing measurable** (-0.01, interval -0.07 to +0.06).
- **A bigger step budget does not help.** With 30 steps instead of 15, Nemotron v1 mostly stops on its own (only 15% of its fault runs reach the 30-step limit), yet it scores no better (-0.04, interval -0.16 to +0.06) for 2.4 times the tokens.
- **One run is not enough, and stated confidence overstates accuracy.** At temperature 0, all five runs of Nemotron v1 give the same top answer on only 8 of 20 incidents. Every agent states more confidence than it earns, Gemini the most (0.91 stated vs 0.53 right).

## The numbers

Accuracy on the 16 fault incidents, and the share of control runs answered correctly ("no incident"), with and without control-2 (see Caveats):

| solver | model | tools | fault incidents | controls | controls without control-2 | runs |
|---|---|---|---|---|---|---|
| heuristic | none | change ranking | 0.59 | 0.75 | 1.00 | 1 per incident |
| agent v0 | Gemini 3.5 Flash-Lite | naive | 0.47 | 1.00 | 1.00 | 100/100 |
| agent v1 | Gemini 3.5 Flash-Lite | change-aware | 0.41 | 1.00 | 1.00 | 100/100 |
| agent v0 | Nemotron 3 Super | naive | 0.69 | 0.30 | 0.40 | 100/100 |
| agent v1 | Nemotron 3 Super | change-aware | 0.68 | 0.50 | 0.67 | 100/100 |
| agent v0 | Nemotron 3.5 Super | naive | 0.73 | 0.60 | 0.73 | 100/100 |
| agent v1 | Nemotron 3.5 Super | change-aware | 0.73 | 0.65 | 0.87 | 100/100 |
| agent v1 | GLM 5.3 Flash | change-aware | 0.73 | 0.80 | 0.80 | 100/100 |
| agent v1, no priors | Nemotron 3 Super | change-aware | 0.67 | 0.50 | 0.67 | 100/100 |
| agent v1, vague alert | Nemotron 3 Super | change-aware | 0.56 | 0.25 | 0.33 | 100/100 |
| agent v1, 30-step limit | Nemotron 3 Super | change-aware | 0.63 | 0.55 | 0.73 | 100/100 |
| agent v1, vague alert | Gemini 3.5 Flash-Lite | change-aware | 0.28 | 0.75 | 1.00 | 60/60 |

The paired comparisons compare each solver's mean score per incident with another's on the same incidents. The interval is a 95% bootstrap over incidents, and p is an exact paired permutation test, both on the 16 fault incidents. With this few incidents, an interval that includes 0 means the benchmark cannot tell the two apart. The last two columns repeat the comparison over all 20 incidents, the controls included, so false alarms count too.

| comparison | wins / ties / losses | mean difference | 95% interval | p | with controls | 95% interval (all 20) |
|---|---|---|---|---|---|---|
| Nemotron v1 vs Gemini v1 (model) | 9 / 5 / 2 | +0.26 | +0.10 to +0.44 | 0.01 | +0.11 | -0.09 to +0.31 |
| Nemotron v0 vs Gemini v0 (model) | 9 / 4 / 3 | +0.23 | +0.04 to +0.41 | 0.05 | +0.04 | -0.19 to +0.26 |
| GLM v1 vs Gemini v1 (model) | 9 / 5 / 2 | +0.32 | +0.09 to +0.56 | 0.03 | +0.21 | +0.00 to +0.43 |
| Nemotron 3.5 v1 vs Nemotron v1 (newer version) | 5 / 10 / 1 | +0.06 | -0.01 to +0.12 | 0.19 | +0.07 | -0.00 to +0.16 |
| Nemotron 3.5 v0 vs Nemotron v0 (newer version) | 4 / 10 / 2 | +0.04 | -0.05 to +0.12 | 0.62 | +0.09 | -0.02 to +0.21 |
| Nemotron v1 vs heuristic | 5 / 8 / 3 | +0.08 | -0.05 to +0.23 | 0.31 | +0.01 | -0.11 to +0.15 |
| Nemotron v0 vs heuristic | 6 / 4 / 6 | +0.10 | -0.15 to +0.35 | 0.49 | -0.01 | -0.24 to +0.23 |
| Nemotron 3.5 v1 vs heuristic | 6 / 7 / 3 | +0.14 | -0.02 to +0.33 | 0.21 | +0.09 | -0.05 to +0.25 |
| Nemotron 3.5 v0 vs heuristic | 6 / 6 / 4 | +0.14 | -0.13 to +0.41 | 0.37 | +0.08 | -0.16 to +0.32 |
| GLM v1 vs heuristic | 5 / 9 / 2 | +0.14 | -0.09 to +0.38 | 0.34 | +0.12 | -0.09 to +0.33 |
| Nemotron v1 vs Nemotron v0 (tools) | 6 / 4 / 6 | -0.02 | -0.14 to +0.11 | 0.86 | +0.03 | -0.09 to +0.14 |
| Gemini v1 vs Gemini v0 (tools) | 5 / 6 / 5 | -0.06 | -0.23 to +0.10 | 0.60 | -0.05 | -0.18 to +0.08 |
| Nemotron 3.5 v1 vs Nemotron 3.5 v0 (tools) | 4 / 8 / 4 | -0.00 | -0.17 to +0.17 | 1.00 | +0.01 | -0.14 to +0.15 |
| Nemotron v1, vague alert vs Nemotron v1 | 1 / 9 / 6 | -0.12 | -0.25 to -0.01 | 0.09 | -0.15 | -0.26 to -0.05 |
| Gemini v1, vague alert vs Gemini v1 | 1 / 7 / 8 | -0.13 | -0.27 to -0.01 | 0.07 | -0.16 | -0.29 to -0.03 |
| Nemotron v1, no priors vs Nemotron v1 | 4 / 8 / 4 | -0.01 | -0.07 to +0.06 | 1.00 | -0.00 | -0.07 to +0.07 |
| Nemotron v1, 30 steps vs Nemotron v1 (15) | 4 / 7 / 5 | -0.04 | -0.16 to +0.06 | 0.53 | -0.03 | -0.14 to +0.09 |
| Gemini v0 vs heuristic | 3 / 5 / 8 | -0.12 | -0.39 to +0.17 | 0.44 | -0.05 | -0.29 to +0.20 |
| Gemini v1 vs heuristic | 3 / 7 / 6 | -0.18 | -0.40 to +0.02 | 0.15 | -0.10 | -0.30 to +0.11 |

These are about twenty comparisons with no multiple-comparison correction, so a single interval that only just excludes 0 is suggestive, not established.

## Findings

### 1. The model, not the toolset, separates the agents on fault incidents

Gemini 3.5 Flash-Lite and Nemotron 3 Super get the same prompt, tools and step limit, yet the gap on fault incidents is +0.26. Much of it comes from what each model does when it runs out of steps. An agent still calling tools at its 15-turn limit is told to answer:

| solver | fault runs | hit the limit | then said "no incident" | accuracy when hit | accuracy otherwise |
|---|---|---|---|---|---|
| Gemini v1 | 80 | 49 (61%) | 27 of 49 | 0.29 | 0.61 |
| Nemotron v1 | 80 | 54 (68%) | 2 of 54 | 0.63 | 0.77 |

When Gemini Flash-Lite is cut off, it often concludes that nothing is wrong. That happens even when its first tool call ranked the fault first. On ad-high-cpu, `top_changes` put ad's CPU at the top (+163x), and all five v1 runs still answered "no incident" (confidence 0.8-0.95). Nemotron names its best suspect. When Gemini finishes on its own, its accuracy (0.61) is close to Nemotron v1's when cut off (0.63).

Two more models run through the same agent confirm the size of the model effect: GLM 5.3 Flash scores 0.32 above Gemini on fault incidents (interval +0.09 to +0.56), while Nemotron 3.5 Super, a newer version of Nemotron, is not measurably better than Nemotron 3 Super (+0.06, interval -0.01 to +0.12). A model change can matter a lot; a version bump within one model family did not here.

The same habit is why the gap shrinks once the controls count. Gemini's perfect control score is the other side of its "no incident" answers, not better judgement, and Nemotron's false alarms (35% of control runs for v1) cancel most of its lead: over all 20 incidents the difference is +0.11, and its interval includes 0.

### 2. The change-aware tools move accuracy around

On Gemini, v1's tools change nothing measurable either (0.41 against v0's 0.47; paired -0.06, interval -0.23 to +0.10), because Gemini's errors are mostly "no incident" with either toolset. On Nemotron the overall score is the same with v0's naive tools (raw metric series, trace and log search) and v1's change-aware ones (`top_changes`, `service_health`, `service_map`), but the categories differ:

| category | Nemotron v0 (naive) | Nemotron v1 (change-aware) |
|---|---|---|
| cross-service (3 incidents) | 0.67 | 0.33 |
| silent (6) | 0.63 | 0.80 |
| two-fault (2) | 0.45 | 0.60 |
| controls (4), answered correctly | 0.30 | 0.50 |

- **Fewer false alarms.**
  - Nemotron v0 raised an incident on 60% of control runs, v1 on 35%.
  - Excluding control-2, where a real, unprompted payment latency spike happened during the no-fault window (see Caveats), the counts are 7 of 15 for v0 and 2 of 15 for v1.
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

### Where the wrong answers come from

The report's failure-mode table sorts every wrong run on a fault incident, each counted once, in the first matching column from the left:

| solver | wrong runs | said no incident | abstained | found one of two causes | true cause ranked 2nd or 3rd | named the top-changed service | another wrong service |
|---|---|---|---|---|---|---|---|
| Gemini v1 | 49 | **34** | 0 | 4 | 2 | 9 | 0 |
| Nemotron v0 | 29 | 0 | 3 | 9 | 2 | 5 | 10 |
| Nemotron v1 | 29 | 2 | 1 | 6 | **10** | 8 | 2 |

- **Gemini's errors are mostly "no incident"** (34 of 49).
- **Nemotron v1 is usually close:**
  - in 10 of its 29 wrong runs, the true cause is in its answer, just not first;
  - in 8 more, it named the service with the largest rise in the change table, which is where the symptom shows and also the heuristic's whole method.
- **The naive tools fail differently:**
  - Nemotron v0 names an unrelated service (10) or abstains (3) more often, and rarely ranks the true cause second (2);
  - v1's change ranking moves its mistakes toward the top-changed service.

A rule that blames a stopped or erroring dependency of the top-changed service looks like the obvious fix. On the two cross-service incidents in the tuning split it does not hold up:
- on payment-unreachable, two dependencies stop at once (payment and email), and the traces cannot tell them apart;
- on kafka-queue-problems, the call map has no Kafka edge.

With two examples it would be fitting a rule to the test, so it was not built.

### 3. The alert probably carries real information

The vague-alert ablation gives every incident the same alert: "Users report that something is wrong with the shop." Against Nemotron v1, the clearest effect is on the controls: false alarms double, from 35% to 70% of control runs, and correct control runs fall from 0.50 to 0.25. Accuracy on fault incidents falls from 0.68 to 0.56 (paired -0.12, interval -0.25 to -0.01, permutation p = 0.09), a borderline drop that two incidents drive most of. Over all 20 incidents the drop is -0.15 (interval -0.26 to -0.05). Part of any agent's edge over the heuristic, which never reads the alert, is reading it. Several alerts name the functional area of the cause; `scenarios/NOTES.md` lists them.

### 4. The prompt's two priors do not matter

v1's prompt contains two sentences: "the service the alert mentions is often NOT the cause" and "it is possible that nothing is actually wrong". Removing them changes nothing measurable on Nemotron: -0.01 on fault incidents, the same 0.50 on controls, and 4 wins and 4 losses.

### 5. A bigger step budget does not help

Nemotron v1 hits its 15-turn limit on 68% of its fault runs, and does worse when it does (0.63 against 0.77). So the step limit looked like a cause. With a 30-step limit:

| | 15 steps | 30 steps |
|---|---|---|
| fault incidents | 0.68 | 0.63 |
| controls answered correctly | 0.50 | 0.55 |
| fault runs that hit the limit | 68% | 15% |
| prompt tokens per run (mean) | 94k | 224k |
| tokens per correct run | 153k | 374k |

With twice the budget, Nemotron mostly stops on its own: 48 of its 80 fault runs finish in 15-29 turns, 2 more answer on the 30th, and only 12 reach the limit. Yet accuracy does not rise (paired -0.04, interval -0.16 to +0.06), at 2.4 times the tokens, so the budget is not what limits accuracy. The runs cut off at 15 turns are more likely the harder incidents than ones a bigger budget would rescue. The 15-step limit stays.

### 6. Runs are not repeatable, and confidence is inflated

Temperature 0 does not make a hosted model deterministic:

| solver | incidents where all runs agree | pairwise agreement | mean confidence | accuracy | calibration error (ECE) |
|---|---|---|---|---|---|
| Gemini v1 | 12 of 20 | 0.80 | 0.91 | 0.53 | 0.38 |
| Nemotron v0 | 6 of 20 | 0.54 | 0.82 | 0.61 | 0.20 |
| Nemotron v1 | 8 of 20 | 0.66 | 0.87 | 0.64 | 0.23 |
| Nemotron v1, vague alert | 9 of 20 | 0.58 | 0.85 | 0.49 | 0.36 |

(Accuracy and confidence here are over every run, controls included. ECE is over 5 equal-width confidence bins.)

- **A single run would be misleading.** On 12 of 20 incidents, Nemotron v1's five runs disagree on the top answer. This is why every agent batch is planned at 5 runs (3 for the Gemini ablations) and the report averages per incident before comparing.
- **Gemini is more repeatable but more wrong.** Its runs agree more often (0.80). The agreement includes its repeated "no incident" answers (see finding 1).
- **Every agent is overconfident.** Stated confidence is 0.2-0.4 above accuracy. The vague alert makes this worse: accuracy drops but confidence barely moves. Confidence alone is not a usable signal for when to trust an answer; the coverage curve in `report.md` shows the same.

## Models tried

Besides Gemini 3.5 Flash-Lite and Nemotron 3 Super, the agents ran unchanged (prompt, tools, step limit) on two more models through `eval --model`, both on NVIDIA's free endpoint:
- **Nemotron 3.5 Super** (`nvidia/nemotron-3.5-super-vl-120b-a12b`): agents v1 and v0, complete. It was the fastest model tried, at about 90 seconds per run.
- **GLM 5.3 Flash** (`z-ai/glm-5.3-flash`): agent v1, complete.
- **Gemma 4 26B** (Gemini endpoint) timed out on almost every request in two attempts (2026-10-16 and 2026-10-18). Its single completed run is set aside and not reported.
- **Not run:** GLM 5.3, DeepSeek V4.1 Flash and Gemma 4 31B on the NVIDIA endpoint, and Gemma 4 31B on the Gemini endpoint, all timed out or returned errors when tried on 2026-10-18; DeepSeek V4.1 Flash timed out again on 2026-10-19.

## Caveats

- **Controls are noisy.** control-2 contains a real latency spike (payment p95 8 ms → 7.5 s) in a window with no injected fault. The scoring rules, fixed in advance, count any incident answer on a control as wrong. Every run that calls an incident there, the heuristic's included, is marked down, although the spike is real. The table above gives control accuracy without it as well.
- **Sixteen fault incidents, one demo app.** Category numbers rest on 2-6 incidents each.
- **Held out.** One held-out incident's v1 tool output was viewed during development; see the Provenance section of `report.md`.
- **Temperature 0.** The 5-run spread measures nondeterminism in the model APIs, not sampling.
- **Gemini no-priors ablation running.** It is quota-bound; `report.md` shows it as partial and this page will add it when it finishes.
- More threats to validity, in plain words, are in the [methodology FAQ](../faq.md).

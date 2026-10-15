# RootCause evaluation report

## Accuracy by category

Accuracy is the mean over scenarios of each scenario's mean; ± is the sd across run indices (shown when at least two complete runs exist). The held-out split was frozen before any agent-v1 tuning.

### Split: all

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague | agent-v1-nemotron-steps30 | agent-v1@gemma-4-26b-a4b-it | hunch-0.6b | hunch-1.7b | laya-english | laya-multilingual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| easy | 0.67 ± - (3/3 sc, 1 run) | 0.67 ± - (3/3 sc, 1-2 runs) | 0.67 ± 0.00 (3/3 sc, 5 runs) | not run | not run | 1.00 ± 0.00 (3/3 sc, 5 runs) | 0.87 ± 0.16 (3/3 sc, 5 runs) | 0.93 ± 0.13 (3/3 sc, 5 runs) | 0.87 ± 0.16 (3/3 sc, 5 runs) | 1.00 ± - (3/3 sc, 1-2 runs) | 1.00 ± - (1/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.33 ± - (3/3 sc, 1 run) |
| hard-cross-service | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1-2 runs) | 0.08 ± 0.14 (3/3 sc, 4-5 runs) | not run | not run | 0.67 ± 0.21 (3/3 sc, 5 runs) | 0.33 ± 0.21 (3/3 sc, 5 runs) | 0.27 ± 0.13 (3/3 sc, 5 runs) | 0.27 ± 0.25 (3/3 sc, 5 runs) | 0.00 ± - (3/3 sc, 1 run) | - | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) |
| hard-silent | 0.83 ± - (6/6 sc, 1 run) | 0.42 ± - (6/6 sc, 1-2 runs) | 0.45 ± 0.22 (6/6 sc, 4-5 runs) | not run | not run | 0.63 ± 0.12 (6/6 sc, 5 runs) | 0.80 ± 0.12 (6/6 sc, 5 runs) | 0.73 ± 0.13 (6/6 sc, 5 runs) | 0.57 ± 0.08 (6/6 sc, 5 runs) | 0.75 ± - (6/6 sc, 1-2 runs) | - | 0.00 ± - (6/6 sc, 1 run) | 0.00 ± - (6/6 sc, 1 run) | 0.33 ± - (6/6 sc, 1 run) | 0.50 ± - (6/6 sc, 1 run) |
| hard-noisy | 0.50 ± - (2/2 sc, 1 run) | 0.75 ± - (2/2 sc, 1-2 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | not run | not run | 0.70 ± 0.24 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.50 ± - (2/2 sc, 1 run) | - | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.50 ± - (2/2 sc, 1 run) | 0.50 ± - (2/2 sc, 1 run) |
| hard-two-faults | 0.75 ± - (2/2 sc, 1 run) | 0.25 ± - (2/2 sc, 1-2 runs) | 0.20 ± 0.19 (2/2 sc, 5 runs) | not run | not run | 0.45 ± 0.10 (2/2 sc, 5 runs) | 0.60 ± 0.25 (2/2 sc, 5 runs) | 0.75 ± 0.16 (2/2 sc, 5 runs) | 0.45 ± 0.10 (2/2 sc, 5 runs) | 1.00 ± - (2/2 sc, 1 run) | - | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) |
| control | 0.75 ± - (4/4 sc, 1 run) | 1.00 ± 0.00 (4/4 sc, 2 runs) | 1.00 ± 0.00 (4/4 sc, 5 runs) | not run | not run | 0.30 ± 0.19 (4/4 sc, 5 runs) | 0.50 ± 0.16 (4/4 sc, 5 runs) | 0.50 ± 0.16 (4/4 sc, 5 runs) | 0.25 ± 0.16 (4/4 sc, 5 runs) | 0.62 ± - (4/4 sc, 1-2 runs) | - | 1.00 ± - (4/4 sc, 1 run) | 1.00 ± - (4/4 sc, 1 run) | 0.00 ± - (4/4 sc, 1 run) | 0.50 ± - (4/4 sc, 1 run) |
| all incidents | 0.59 ± - (16/16 sc, 1 run) | 0.41 ± - (16/16 sc, 1-2 runs) | 0.41 ± 0.10 (16/16 sc, 4-5 runs) | not run | not run | 0.69 ± 0.07 (16/16 sc, 5 runs) | 0.68 ± 0.04 (16/16 sc, 5 runs) | 0.67 ± 0.05 (16/16 sc, 5 runs) | 0.56 ± 0.12 (16/16 sc, 5 runs) | 0.66 ± - (16/16 sc, 1-2 runs) | 1.00 ± - (1/16 sc, 1 run) | 0.00 ± - (16/16 sc, 1 run) | 0.00 ± - (16/16 sc, 1 run) | 0.19 ± - (16/16 sc, 1 run) | 0.31 ± - (16/16 sc, 1 run) |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (4-5 runs per scenario, 97/100 runs)

agent-v1-nemotron-steps30: partial batch (1-2 runs per scenario, 26/100 runs)

agent-v1@gemma-4-26b-a4b-it: partial batch (0-1 runs per scenario, 1/100 runs)

### Split: tune

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague | agent-v1-nemotron-steps30 | agent-v1@gemma-4-26b-a4b-it | hunch-0.6b | hunch-1.7b | laya-english | laya-multilingual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| easy | 1.00 ± - (2/2 sc, 1 run) | 0.50 ± - (2/2 sc, 1-2 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | not run | not run | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± - (2/2 sc, 1-2 runs) | 1.00 ± - (1/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) |
| hard-cross-service | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1-2 runs) | 0.00 ± 0.00 (2/2 sc, 5 runs) | not run | not run | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.30 ± 0.24 (2/2 sc, 5 runs) | 0.30 ± 0.24 (2/2 sc, 5 runs) | 0.20 ± 0.24 (2/2 sc, 5 runs) | 0.00 ± - (2/2 sc, 1 run) | - | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1 run) |
| hard-silent | 0.80 ± - (5/5 sc, 1 run) | 0.50 ± - (5/5 sc, 1-2 runs) | 0.54 ± 0.26 (5/5 sc, 4-5 runs) | not run | not run | 0.60 ± 0.18 (5/5 sc, 5 runs) | 0.76 ± 0.15 (5/5 sc, 5 runs) | 0.68 ± 0.16 (5/5 sc, 5 runs) | 0.48 ± 0.10 (5/5 sc, 5 runs) | 0.70 ± - (5/5 sc, 1-2 runs) | - | 0.00 ± - (5/5 sc, 1 run) | 0.00 ± - (5/5 sc, 1 run) | 0.40 ± - (5/5 sc, 1 run) | 0.40 ± - (5/5 sc, 1 run) |
| hard-noisy | 0.00 ± - (1/1 sc, 1 run) | 0.50 ± 0.50 (1/1 sc, 2 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | not run | not run | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.00 ± - (1/1 sc, 1 run) | - | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) |
| hard-two-faults | 0.50 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 2 runs) | 0.10 ± 0.20 (1/1 sc, 5 runs) | not run | not run | 0.40 ± 0.20 (1/1 sc, 5 runs) | 0.50 ± 0.32 (1/1 sc, 5 runs) | 0.60 ± 0.20 (1/1 sc, 5 runs) | 0.40 ± 0.20 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | - | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) |
| control | 0.67 ± - (3/3 sc, 1 run) | 1.00 ± 0.00 (3/3 sc, 2 runs) | 1.00 ± 0.00 (3/3 sc, 5 runs) | not run | not run | 0.33 ± 0.21 (3/3 sc, 5 runs) | 0.53 ± 0.16 (3/3 sc, 5 runs) | 0.40 ± 0.13 (3/3 sc, 5 runs) | 0.27 ± 0.13 (3/3 sc, 5 runs) | 0.50 ± 0.17 (3/3 sc, 2 runs) | - | 1.00 ± - (3/3 sc, 1 run) | 1.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1 run) | 0.67 ± - (3/3 sc, 1 run) |
| all incidents | 0.59 ± - (11/11 sc, 1 run) | 0.36 ± - (11/11 sc, 1-2 runs) | 0.45 ± 0.11 (11/11 sc, 4-5 runs) | not run | not run | 0.64 ± 0.08 (11/11 sc, 5 runs) | 0.65 ± 0.05 (11/11 sc, 5 runs) | 0.64 ± 0.08 (11/11 sc, 5 runs) | 0.49 ± 0.11 (11/11 sc, 5 runs) | 0.59 ± - (11/11 sc, 1-2 runs) | 1.00 ± - (1/11 sc, 1 run) | 0.00 ± - (11/11 sc, 1 run) | 0.00 ± - (11/11 sc, 1 run) | 0.18 ± - (11/11 sc, 1 run) | 0.27 ± - (11/11 sc, 1 run) |

agent-v0: partial batch (1-2 runs per scenario, 25/70 runs)

agent-v1: partial batch (4-5 runs per scenario, 69/70 runs)

agent-v1-nemotron-steps30: partial batch (1-2 runs per scenario, 20/70 runs)

agent-v1@gemma-4-26b-a4b-it: partial batch (0-1 runs per scenario, 1/70 runs)

### Split: heldout

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague | agent-v1-nemotron-steps30 | agent-v1@gemma-4-26b-a4b-it | hunch-0.6b | hunch-1.7b | laya-english | laya-multilingual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| easy | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 5 runs) | not run | not run | 1.00 ± 0.00 (1/1 sc, 5 runs) | 0.60 ± 0.49 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.60 ± 0.49 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | not run | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) |
| hard-cross-service | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.25 ± 0.43 (1/1 sc, 4 runs) | not run | not run | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.00 ± - (1/1 sc, 1 run) | not run | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) |
| hard-silent | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 4 runs) | not run | not run | 0.80 ± 0.40 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | not run | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) |
| hard-noisy | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± 0.00 (1/1 sc, 5 runs) | not run | not run | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | not run | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) |
| hard-two-faults | 1.00 ± - (1/1 sc, 1 run) | 0.50 ± - (1/1 sc, 1 run) | 0.30 ± 0.24 (1/1 sc, 5 runs) | not run | not run | 0.50 ± 0.00 (1/1 sc, 5 runs) | 0.70 ± 0.24 (1/1 sc, 5 runs) | 0.90 ± 0.20 (1/1 sc, 5 runs) | 0.50 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | not run | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) |
| control | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± 0.00 (1/1 sc, 2 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | not run | not run | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 1.00 ± - (1/1 sc, 1 run) | not run | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) |
| all incidents | 0.60 ± - (5/5 sc, 1 run) | 0.50 ± - (5/5 sc, 1 run) | 0.31 ± 0.07 (5/5 sc, 4-5 runs) | not run | not run | 0.82 ± 0.10 (5/5 sc, 5 runs) | 0.74 ± 0.14 (5/5 sc, 5 runs) | 0.74 ± 0.15 (5/5 sc, 5 runs) | 0.70 ± 0.18 (5/5 sc, 5 runs) | 0.80 ± - (5/5 sc, 1 run) | not run | 0.00 ± - (5/5 sc, 1 run) | 0.00 ± - (5/5 sc, 1 run) | 0.20 ± - (5/5 sc, 1 run) | 0.40 ± - (5/5 sc, 1 run) |

agent-v0: partial batch (1-2 runs per scenario, 7/30 runs)

agent-v1: partial batch (4-5 runs per scenario, 28/30 runs)

agent-v1-nemotron-steps30: partial batch (1 runs per scenario, 6/30 runs)

Held-out categories have one scenario each; read the all-incidents row.

![accuracy by category](figures/accuracy_by_category.png)

Bars: accuracy over all scenarios; error bars ± sd across run indices, clipped to 0-1 (none when fewer than two complete runs). A solver with no record in a category has no bar there.

## False alarms and abstentions (all split)

False alarm = claiming an incident on a control; abstain = insufficient evidence on an incident.

| solver | control false-alarm rate | incident abstain rate |
|---|---|---|
| heuristic | 0.25 | 0.00 |
| agent-v0 | 0.00 | 0.00 |
| agent-v1 | 0.00 | 0.00 |
| agent-v1-nopriors | not run | not run |
| agent-v1-vague | not run | not run |
| agent-v0-nemotron | 0.60 | 0.04 |
| agent-v1-nemotron | 0.35 | 0.01 |
| agent-v1-nemotron-nopriors | 0.35 | 0.03 |
| agent-v1-nemotron-vague | 0.70 | 0.06 |
| agent-v1-nemotron-steps30 | 0.38 | 0.00 |
| agent-v1@gemma-4-26b-a4b-it | - | 0.00 |
| hunch-0.6b | 0.00 | 0.00 |
| hunch-1.7b | 0.00 | 0.00 |
| laya-english | 1.00 | 0.00 |
| laya-multilingual | 0.50 | 0.00 |

## Evidence (all split, incidents)

Grounded = cited evidence exists in the snapshot; distinctive = it also looks anomalous against the baseline (neither proves that the incident caused it).

| solver | grounded | distinctive |
|---|---|---|
| heuristic | 1.00 | 1.00 |
| agent-v0 | n/a (predates evidence checks) | n/a (predates evidence checks) |
| agent-v1 | 1.00 | 0.88 |
| agent-v1-nopriors | not run | not run |
| agent-v1-vague | not run | not run |
| agent-v0-nemotron | n/a (free-text evidence) | n/a (free-text evidence) |
| agent-v1-nemotron | 0.98 | 0.89 |
| agent-v1-nemotron-nopriors | 0.94 | 0.85 |
| agent-v1-nemotron-vague | 0.97 | 0.90 |
| agent-v1-nemotron-steps30 | 0.97 | 0.90 |
| agent-v1@gemma-4-26b-a4b-it | 1.00 | 1.00 |
| hunch-0.6b | - | - |
| hunch-1.7b | - | - |
| laya-english | - | - |
| laya-multilingual | - | - |

## Paired comparisons (all split, fault incidents)

Each solver's mean score per incident, compared on the incidents both have run. Wins / ties / losses count incidents where the first solver scored higher / the same / lower, by any margin. A per-incident mean of 0.5 can mean one of two causes found or half of the runs right. The 95% interval is a percentile bootstrap over incidents (10,000 resamples, fixed seed); at this few incidents it is approximate and somewhat too narrow, and it is not given below 5 shared incidents. An interval that includes 0 means this benchmark cannot tell the two apart.

| comparison | incidents | wins / ties / losses | mean difference | 95% interval |
|---|---|---|---|---|
| agent-v0 vs heuristic | 16/16 | 3 / 6 / 7 | -0.19 | -0.50 to +0.12 |
| agent-v1 vs heuristic | 16/16 | 3 / 7 / 6 | -0.18 | -0.40 to +0.02 |
| agent-v1 vs agent-v0 | 16/16 | 4 / 7 / 5 | +0.00 | -0.21 to +0.22 |
| agent-v0-nemotron vs heuristic | 16/16 | 6 / 4 / 6 | +0.10 | -0.15 to +0.35 |
| agent-v1-nemotron vs heuristic | 16/16 | 5 / 8 / 3 | +0.08 | -0.05 to +0.23 |
| agent-v1-nemotron vs agent-v1 | 16/16 | 9 / 5 / 2 | +0.27 | +0.11 to +0.43 |
| agent-v1-nemotron vs agent-v0-nemotron | 16/16 | 6 / 4 / 6 | -0.02 | -0.14 to +0.11 |
| agent-v1-nemotron-nopriors vs agent-v1-nemotron | 16/16 | 4 / 8 / 4 | -0.01 | -0.07 to +0.06 |
| agent-v1-nemotron-vague vs agent-v1-nemotron | 16/16 | 1 / 9 / 6 | -0.12 | -0.25 to -0.01 |
| agent-v1-nemotron-steps30 vs agent-v1-nemotron | 16/16 | 4 / 7 / 5 | -0.02 | -0.16 to +0.12 |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (4-5 runs per scenario, 97/100 runs)

agent-v1-nemotron-steps30: partial batch (1-2 runs per scenario, 26/100 runs)

## Failure modes (all split, wrong fault-incident runs)

How each wrong run on a fault incident went wrong. The top-changed service is the one with the largest rise in the incident's change table, usually where the symptom shows; naming it is the heuristic's whole method and its typical mistake.

| solver | wrong runs | said no incident | named the top-changed service | true cause ranked 2nd or 3rd | found one of two causes | another wrong service | abstained |
|---|---|---|---|---|---|---|---|
| heuristic | 7 | 0 | 3 | 3 | 1 | 0 | 0 |
| agent-v0 | 15 | 10 | 2 | 2 | 1 | 0 | 0 |
| agent-v1 | 47 | 33 | 8 | 2 | 4 | 0 | 0 |
| agent-v0-nemotron | 29 | 0 | 5 | 2 | 9 | 10 | 3 |
| agent-v1-nemotron | 29 | 2 | 8 | 10 | 6 | 2 | 1 |
| agent-v1-nemotron-nopriors | 29 | 0 | 7 | 13 | 5 | 2 | 2 |
| agent-v1-nemotron-vague | 40 | 3 | 12 | 5 | 9 | 6 | 5 |
| agent-v1-nemotron-steps30 | 6 | 0 | 3 | 2 | 0 | 1 | 0 |
| agent-v1@gemma-4-26b-a4b-it | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hunch-0.6b | 16 | 16 | 0 | 0 | 0 | 0 | 0 |
| hunch-1.7b | 16 | 16 | 0 | 0 | 0 | 0 | 0 |
| laya-english | 13 | 0 | 4 | 5 | 0 | 4 | 0 |
| laya-multilingual | 11 | 10 | 0 | 1 | 0 | 0 | 0 |

## Step limit (all split, fault runs)

An agent that is still calling tools after 15 model turns is told to give its final answer. This splits each agent's fault runs by whether that happened: how many hit the limit, how many of those then answered "no incident", and the accuracy (mean over runs, not per scenario) with and without hitting it.

| solver | fault runs | hit the limit | then said no incident | accuracy when hit | accuracy otherwise |
|---|---|---|---|---|---|
| agent-v0 | 24 | 9 (38%) | 3 of 9 | 0.56 | 0.30 |
| agent-v1 | 77 | 51 (66%) | 28 of 51 | 0.31 | 0.62 |
| agent-v0-nemotron | 80 | 77 (96%) | 0 of 77 | 0.69 | 0.67 |
| agent-v1-nemotron | 80 | 57 (71%) | 2 of 57 | 0.61 | 0.83 |
| agent-v1-nemotron-nopriors | 80 | 53 (66%) | 0 of 53 | 0.62 | 0.76 |
| agent-v1-nemotron-vague | 80 | 64 (80%) | 3 of 64 | 0.51 | 0.75 |
| agent-v1-nemotron-steps30 | 19 | 14 (74%) | 0 of 14 | 0.71 | 0.60 |
| agent-v1@gemma-4-26b-a4b-it | 1 | 1 (100%) | 0 of 1 | 1.00 | - |

## Run-to-run agreement (all incidents)

The agents run at temperature 0, yet their runs still differ, so this measures how far a single run can be trusted. A run's top answer is its first cause's service, or its verdict when it names no cause. Pairwise agreement is the share of run pairs on a scenario that give the same top answer, averaged over the scenarios with at least 2 runs; controls included. With fewer runs per scenario every run agrees more easily, so compare complete batches only.

| solver | scenarios with 2+ runs | every run agrees | pairwise agreement |
|---|---|---|---|
| agent-v0 | 12 | 9 of 12 | 0.75 |
| agent-v1 | 20 | 12 of 20 | 0.79 |
| agent-v0-nemotron | 20 | 6 of 20 | 0.54 |
| agent-v1-nemotron | 20 | 8 of 20 | 0.66 |
| agent-v1-nemotron-nopriors | 20 | 8 of 20 | 0.65 |
| agent-v1-nemotron-vague | 20 | 9 of 20 | 0.58 |
| agent-v1-nemotron-steps30 | 6 | 4 of 6 | 0.67 |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (4-5 runs per scenario, 97/100 runs)

agent-v1-nemotron-steps30: partial batch (1-2 runs per scenario, 26/100 runs)

## Calibration (all incidents, record-level)

A well-calibrated agent's mean stated confidence matches its accuracy. Accuracy here is the mean `correct` over runs, controls included, not the tables' mean over scenarios. ECE (expected calibration error) splits the runs into 5 equal-width confidence bins and sums, over the bins, the bin's share of runs times |mean confidence - accuracy|. Brier is the mean of (confidence - correct)^2. Lower is better for both. Every agent here states a mean confidence above its accuracy: all of them are overconfident.

| solver | runs | mean confidence | accuracy | ECE | Brier |
|---|---|---|---|---|---|
| agent-v0 | 32 | 0.93 | 0.55 | 0.38 | 0.37 |
| agent-v1 | 97 | 0.91 | 0.54 | 0.37 | 0.36 |
| agent-v0-nemotron | 100 | 0.82 | 0.61 | 0.20 | 0.23 |
| agent-v1-nemotron | 100 | 0.87 | 0.64 | 0.23 | 0.25 |
| agent-v1-nemotron-nopriors | 100 | 0.87 | 0.64 | 0.24 | 0.26 |
| agent-v1-nemotron-vague | 100 | 0.85 | 0.49 | 0.36 | 0.33 |
| agent-v1-nemotron-steps30 | 26 | 0.89 | 0.65 | 0.24 | 0.29 |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (4-5 runs per scenario, 97/100 runs)

agent-v1-nemotron-steps30: partial batch (1-2 runs per scenario, 26/100 runs)

## Cost

The heuristic makes no model calls, so it has no token usage.

| solver | runs with usage / records | requests (mean) | requests (max) | prompt tokens (mean) | completion tokens (mean) | tokens per correct run |
|---|---|---|---|---|---|---|
| heuristic | 0 / 20 | - | - | - | - | - |
| agent-v0 | 32 / 32 | 11.50 | 16 | 68442 | 660 | 126356 |
| agent-v1 | 97 / 97 | 14.30 | 16 | 76925 | 523 | 144470 |
| agent-v1-nopriors | not run | not run | not run | not run | not run | not run |
| agent-v1-vague | not run | not run | not run | not run | not run | not run |
| agent-v0-nemotron | 100 / 100 | 15.96 | 17 | 74265 | 3274 | 126080 |
| agent-v1-nemotron | 100 / 100 | 15.06 | 17 | 94309 | 3761 | 153234 |
| agent-v1-nemotron-nopriors | 100 / 100 | 14.85 | 17 | 89252 | 3534 | 146119 |
| agent-v1-nemotron-vague | 100 / 100 | 15.17 | 17 | 89947 | 3687 | 189160 |
| agent-v1-nemotron-steps30 | 26 / 26 | 22.19 | 31 | 221142 | 5827 | 347128 |
| agent-v1@gemma-4-26b-a4b-it | 1 / 1 | 16.00 | 16 | 117918 | 557 | 118475 |
| hunch-0.6b | 0 / 20 | - | - | - | - | - |
| hunch-1.7b | 0 / 20 | - | - | - | - | - |
| laya-english | 0 / 20 | - | - | - | - | - |
| laya-multilingual | 0 / 20 | - | - | - | - | - |

## Per-scenario accuracy

`*` marks held-out scenarios; each cell is the mean over that scenario's runs, with the number of runs.

| scenario | category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague | agent-v1-nemotron-steps30 | agent-v1@gemma-4-26b-a4b-it | hunch-0.6b | hunch-1.7b | laya-english | laya-multilingual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ad-failure | easy | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (2 runs) | 1.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| ad-high-cpu | hard-silent | 1.00 (1 run) | 0.00 (2 runs) | 0.00 (5 runs) | not run | not run | 0.00 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) | 0.00 (5 runs) | 0.50 (2 runs) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| checkout-cpu-throttle | hard-silent | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 0.60 (5 runs) | 0.80 (5 runs) | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (2 runs) | - | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) |
| control-1 | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 0.40 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) | 0.20 (5 runs) | 1.00 (2 runs) | - | 1.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| control-2 | control | 0.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (2 runs) | - | 1.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| control-3 | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 0.60 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) | 0.60 (5 runs) | 0.50 (2 runs) | - | 1.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| control-4* | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (5 runs) | not run | not run | 0.20 (5 runs) | 0.40 (5 runs) | 0.80 (5 runs) | 0.20 (5 runs) | 1.00 (1 run) | - | 1.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| email-memory-leak | hard-silent | 1.00 (1 run) | 0.00 (2 runs) | 0.80 (5 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 0.20 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) | 1.00 (1 run) |
| image-slow-load-and-ad-high-cpu | hard-two-faults | 0.50 (1 run) | 0.00 (2 runs) | 0.10 (5 runs) | not run | not run | 0.40 (5 runs) | 0.50 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| image-slow-load | hard-silent | 1.00 (1 run) | 0.50 (2 runs) | 0.40 (5 runs) | not run | not run | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| kafka-queue-problems | hard-cross-service | 0.00 (1 run) | 0.00 (2 runs) | 0.00 (5 runs) | not run | not run | 0.40 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| lock-contention-with-flood | hard-noisy | 0.00 (1 run) | 0.50 (2 runs) | 0.20 (5 runs) | not run | not run | 0.40 (5 runs) | 0.20 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) | 0.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| payment-failure-50 | easy | 1.00 (1 run) | 0.00 (1 run) | 1.00 (5 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| payment-failure-and-recommendation-leak* | hard-two-faults | 1.00 (1 run) | 0.50 (1 run) | 0.30 (5 runs) | not run | not run | 0.50 (5 runs) | 0.70 (5 runs) | 0.90 (5 runs) | 0.50 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| payment-failure-with-flood* | hard-noisy | 1.00 (1 run) | 1.00 (1 run) | 1.00 (5 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) | 0.00 (1 run) |
| payment-unreachable | hard-cross-service | 0.00 (1 run) | 0.00 (1 run) | 0.00 (5 runs) | not run | not run | 0.80 (5 runs) | 0.60 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) | 0.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |
| product-catalog-failure* | easy | 0.00 (1 run) | 1.00 (1 run) | 0.00 (5 runs) | not run | not run | 1.00 (5 runs) | 0.60 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| product-catalog-lock-contention | hard-silent | 0.00 (1 run) | 1.00 (1 run) | 0.50 (4 runs) | not run | not run | 0.60 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) | 0.20 (5 runs) | 0.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| recommendation-cache-leak* | hard-silent | 1.00 (1 run) | 0.00 (1 run) | 0.00 (4 runs) | not run | not run | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 1.00 (1 run) |
| valkey-cart-paused* | hard-cross-service | 0.00 (1 run) | 0.00 (1 run) | 0.25 (4 runs) | not run | not run | 0.80 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) | 0.40 (5 runs) | 0.00 (1 run) | - | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) | 0.00 (1 run) |

## Accuracy vs coverage (all split, record-level)

![accuracy vs coverage](figures/coverage.png)

Coverage is the fraction of all runs whose answer is at or above the confidence threshold (abstentions never count). Accuracy here is over answered runs only, so the lowest-threshold point can exceed the tables' accuracy, which counts abstentions as wrong.

agent-v0: accuracy 0.71 at 59% coverage (the curve point nearest 50%, confidence >= 0.95). Partial batch (1-2 runs per scenario, 32/100 runs): treat with caution.

agent-v1: accuracy 0.67 at 49% coverage (the curve point nearest 50%, confidence >= 0.95). Partial batch (4-5 runs per scenario, 97/100 runs): treat with caution.

agent-v0-nemotron: accuracy 0.73 at 49% coverage (the curve point nearest 50%, confidence >= 0.90).

agent-v1-nemotron: accuracy 0.67 at 70% coverage (the curve point nearest 50%, confidence >= 0.90).

agent-v1-nemotron-nopriors: accuracy 0.60 at 31% coverage (the curve point nearest 50%, confidence >= 0.92).

agent-v1-nemotron-vague: accuracy 0.54 at 68% coverage (the curve point nearest 50%, confidence >= 0.90).

agent-v1-nemotron-steps30: accuracy 0.67 at 23% coverage (the curve point nearest 50%, confidence >= 0.95). Partial batch (1-2 runs per scenario, 26/100 runs): treat with caution.

agent-v1@gemma-4-26b-a4b-it: accuracy 1.00 at 100% coverage (the curve point nearest 50%, confidence >= 1.00). Partial batch (0-1 runs per scenario, 1/100 runs): treat with caution.

## Provenance

Code versions (git short sha) of the records behind each solver:

- heuristic: e53dd3d
- agent-v0: 23ebb5e
- agent-v1: 1edb7ba, 4626c77, 8705d39
- agent-v1-nopriors: not run
- agent-v1-vague: not run
- agent-v0-nemotron: cfa0c6e
- agent-v1-nemotron: 8b4fefb
- agent-v1-nemotron-nopriors: dc26375
- agent-v1-nemotron-vague: dc26375
- agent-v1-nemotron-steps30: 2a14eb4
- agent-v1@gemma-4-26b-a4b-it: 4f2ca2f
- hunch-0.6b: dc26375
- hunch-1.7b: dc26375
- laya-english: 4ca5a14
- laya-multilingual: 4ca5a14

During agent-v1 development, v1 tool output was viewed on one held-out incident (valkey-cart-paused). The one feature it suggested that no tuning snapshot exercised (an incomplete-services list) was removed before any v1 run; the other changes from that time (stopped service-map edges, the 'after = 0 can mean the service stopped reporting' caveat) are each exercised by the tuning snapshot payment-unreachable.

## Not run

Solvers with no recorded runs: agent-v1-nopriors, agent-v1-vague.

A Flash vs Flash-Lite comparison is absent: Flash's free tier allows 20 requests/day and one agent run takes about 12-15 requests (up to 17), so the Gemini agents run on `gemini-3.5-flash-lite` only. The model comparison is instead agent-v1-nemotron: agent v1 unchanged (prompt, tools, step limit) on `nvidia/nemotron-3-super-120b-a12b` through NVIDIA's free trial endpoint.

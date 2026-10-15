# RootCause evaluation report

## Accuracy by category

Accuracy is the mean over scenarios of each scenario's mean; ± is the sd across run indices (shown when at least two complete runs exist). The held-out split was frozen before any agent-v1 tuning.

### Split: all

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague |
|---|---|---|---|---|---|---|---|---|---|
| easy | 0.67 ± - (3/3 sc, 1 run) | 0.67 ± - (3/3 sc, 1-2 runs) | 0.67 ± 0.00 (3/3 sc, 3-4 runs) | not run | not run | 1.00 ± 0.00 (3/3 sc, 5 runs) | 0.87 ± 0.16 (3/3 sc, 5 runs) | 0.93 ± 0.13 (3/3 sc, 5 runs) | 0.87 ± 0.16 (3/3 sc, 5 runs) |
| hard-cross-service | 0.00 ± - (3/3 sc, 1 run) | 0.00 ± - (3/3 sc, 1-2 runs) | 0.11 ± 0.16 (3/3 sc, 3 runs) | not run | not run | 0.67 ± 0.21 (3/3 sc, 5 runs) | 0.33 ± 0.21 (3/3 sc, 5 runs) | 0.27 ± 0.13 (3/3 sc, 5 runs) | 0.27 ± 0.25 (3/3 sc, 5 runs) |
| hard-silent | 0.83 ± - (6/6 sc, 1 run) | 0.42 ± - (6/6 sc, 1-2 runs) | 0.39 ± 0.21 (6/6 sc, 3-4 runs) | not run | not run | 0.63 ± 0.12 (6/6 sc, 5 runs) | 0.80 ± 0.12 (6/6 sc, 5 runs) | 0.73 ± 0.13 (6/6 sc, 5 runs) | 0.57 ± 0.08 (6/6 sc, 5 runs) |
| hard-noisy | 0.50 ± - (2/2 sc, 1 run) | 0.75 ± - (2/2 sc, 1-2 runs) | 0.67 ± 0.24 (2/2 sc, 3 runs) | not run | not run | 0.70 ± 0.24 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.60 ± 0.20 (2/2 sc, 5 runs) |
| hard-two-faults | 0.75 ± - (2/2 sc, 1 run) | 0.25 ± - (2/2 sc, 1-2 runs) | 0.17 ± 0.24 (2/2 sc, 3 runs) | not run | not run | 0.45 ± 0.10 (2/2 sc, 5 runs) | 0.60 ± 0.25 (2/2 sc, 5 runs) | 0.75 ± 0.16 (2/2 sc, 5 runs) | 0.45 ± 0.10 (2/2 sc, 5 runs) |
| control | 0.75 ± - (4/4 sc, 1 run) | 1.00 ± 0.00 (4/4 sc, 2 runs) | 1.00 ± 0.00 (4/4 sc, 3-4 runs) | not run | not run | 0.30 ± 0.19 (4/4 sc, 5 runs) | 0.50 ± 0.16 (4/4 sc, 5 runs) | 0.50 ± 0.16 (4/4 sc, 5 runs) | 0.25 ± 0.16 (4/4 sc, 5 runs) |
| all incidents | 0.59 ± - (16/16 sc, 1 run) | 0.41 ± - (16/16 sc, 1-2 runs) | 0.40 ± 0.11 (16/16 sc, 3-4 runs) | not run | not run | 0.69 ± 0.07 (16/16 sc, 5 runs) | 0.68 ± 0.04 (16/16 sc, 5 runs) | 0.67 ± 0.05 (16/16 sc, 5 runs) | 0.56 ± 0.12 (16/16 sc, 5 runs) |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (3-4 runs per scenario, 64/100 runs)

### Split: tune

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague |
|---|---|---|---|---|---|---|---|---|---|
| easy | 1.00 ± - (2/2 sc, 1 run) | 0.50 ± - (2/2 sc, 1-2 runs) | 1.00 ± 0.00 (2/2 sc, 3-4 runs) | not run | not run | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) | 1.00 ± 0.00 (2/2 sc, 5 runs) |
| hard-cross-service | 0.00 ± - (2/2 sc, 1 run) | 0.00 ± - (2/2 sc, 1-2 runs) | 0.00 ± 0.00 (2/2 sc, 3 runs) | not run | not run | 0.60 ± 0.20 (2/2 sc, 5 runs) | 0.30 ± 0.24 (2/2 sc, 5 runs) | 0.30 ± 0.24 (2/2 sc, 5 runs) | 0.20 ± 0.24 (2/2 sc, 5 runs) |
| hard-silent | 0.80 ± - (5/5 sc, 1 run) | 0.50 ± - (5/5 sc, 1-2 runs) | 0.47 ± 0.25 (5/5 sc, 3-4 runs) | not run | not run | 0.60 ± 0.18 (5/5 sc, 5 runs) | 0.76 ± 0.15 (5/5 sc, 5 runs) | 0.68 ± 0.16 (5/5 sc, 5 runs) | 0.48 ± 0.10 (5/5 sc, 5 runs) |
| hard-noisy | 0.00 ± - (1/1 sc, 1 run) | 0.50 ± 0.50 (1/1 sc, 2 runs) | 0.33 ± 0.47 (1/1 sc, 3 runs) | not run | not run | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) |
| hard-two-faults | 0.50 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 2 runs) | 0.17 ± 0.24 (1/1 sc, 3 runs) | not run | not run | 0.40 ± 0.20 (1/1 sc, 5 runs) | 0.50 ± 0.32 (1/1 sc, 5 runs) | 0.60 ± 0.20 (1/1 sc, 5 runs) | 0.40 ± 0.20 (1/1 sc, 5 runs) |
| control | 0.67 ± - (3/3 sc, 1 run) | 1.00 ± 0.00 (3/3 sc, 2 runs) | 1.00 ± 0.00 (3/3 sc, 3-4 runs) | not run | not run | 0.33 ± 0.21 (3/3 sc, 5 runs) | 0.53 ± 0.16 (3/3 sc, 5 runs) | 0.40 ± 0.13 (3/3 sc, 5 runs) | 0.27 ± 0.13 (3/3 sc, 5 runs) |
| all incidents | 0.59 ± - (11/11 sc, 1 run) | 0.36 ± - (11/11 sc, 1-2 runs) | 0.44 ± 0.12 (11/11 sc, 3-4 runs) | not run | not run | 0.64 ± 0.08 (11/11 sc, 5 runs) | 0.65 ± 0.05 (11/11 sc, 5 runs) | 0.64 ± 0.08 (11/11 sc, 5 runs) | 0.49 ± 0.11 (11/11 sc, 5 runs) |

agent-v0: partial batch (1-2 runs per scenario, 25/70 runs)

agent-v1: partial batch (3-4 runs per scenario, 46/70 runs)

### Split: heldout

| category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague |
|---|---|---|---|---|---|---|---|---|---|
| easy | 0.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 3 runs) | not run | not run | 1.00 ± 0.00 (1/1 sc, 5 runs) | 0.60 ± 0.49 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.60 ± 0.49 (1/1 sc, 5 runs) |
| hard-cross-service | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.33 ± 0.47 (1/1 sc, 3 runs) | not run | not run | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) |
| hard-silent | 1.00 ± - (1/1 sc, 1 run) | 0.00 ± - (1/1 sc, 1 run) | 0.00 ± 0.00 (1/1 sc, 3 runs) | not run | not run | 0.80 ± 0.40 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) |
| hard-noisy | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± 0.00 (1/1 sc, 3 runs) | not run | not run | 1.00 ± 0.00 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 1.00 ± 0.00 (1/1 sc, 5 runs) |
| hard-two-faults | 1.00 ± - (1/1 sc, 1 run) | 0.50 ± - (1/1 sc, 1 run) | 0.17 ± 0.24 (1/1 sc, 3 runs) | not run | not run | 0.50 ± 0.00 (1/1 sc, 5 runs) | 0.70 ± 0.24 (1/1 sc, 5 runs) | 0.90 ± 0.20 (1/1 sc, 5 runs) | 0.50 ± 0.00 (1/1 sc, 5 runs) |
| control | 1.00 ± - (1/1 sc, 1 run) | 1.00 ± 0.00 (1/1 sc, 2 runs) | 1.00 ± 0.00 (1/1 sc, 3 runs) | not run | not run | 0.20 ± 0.40 (1/1 sc, 5 runs) | 0.40 ± 0.49 (1/1 sc, 5 runs) | 0.80 ± 0.40 (1/1 sc, 5 runs) | 0.20 ± 0.40 (1/1 sc, 5 runs) |
| all incidents | 0.60 ± - (5/5 sc, 1 run) | 0.50 ± - (5/5 sc, 1 run) | 0.30 ± 0.08 (5/5 sc, 3 runs) | not run | not run | 0.82 ± 0.10 (5/5 sc, 5 runs) | 0.74 ± 0.14 (5/5 sc, 5 runs) | 0.74 ± 0.15 (5/5 sc, 5 runs) | 0.70 ± 0.18 (5/5 sc, 5 runs) |

agent-v0: partial batch (1-2 runs per scenario, 7/30 runs)

agent-v1: partial batch (3 runs per scenario, 18/30 runs)

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

## Paired comparisons (all split, fault incidents)

Each solver's mean score per incident, compared on the incidents both have run. Wins / ties / losses count incidents where the first solver scored higher / the same / lower, by any margin. A per-incident mean of 0.5 can mean one of two causes found or half of the runs right. The 95% interval is a percentile bootstrap over incidents (10,000 resamples, fixed seed); at this few incidents it is approximate and somewhat too narrow, and it is not given below 5 shared incidents. An interval that includes 0 means this benchmark cannot tell the two apart.

| comparison | incidents | wins / ties / losses | mean difference | 95% interval |
|---|---|---|---|---|
| agent-v0 vs heuristic | 16/16 | 3 / 6 / 7 | -0.19 | -0.50 to +0.12 |
| agent-v1 vs heuristic | 16/16 | 3 / 7 / 6 | -0.20 | -0.42 to -0.00 |
| agent-v1 vs agent-v0 | 16/16 | 4 / 7 / 5 | -0.01 | -0.23 to +0.21 |
| agent-v1-nemotron vs heuristic | 16/16 | 5 / 8 / 3 | +0.08 | -0.05 to +0.23 |
| agent-v1-nemotron vs agent-v1 | 16/16 | 10 / 4 / 2 | +0.28 | +0.12 to +0.45 |
| agent-v1-nemotron vs agent-v0-nemotron | 16/16 | 6 / 4 / 6 | -0.02 | -0.14 to +0.11 |
| agent-v1-nemotron-nopriors vs agent-v1-nemotron | 16/16 | 4 / 8 / 4 | -0.01 | -0.07 to +0.06 |
| agent-v1-nemotron-vague vs agent-v1-nemotron | 16/16 | 1 / 9 / 6 | -0.12 | -0.25 to -0.01 |

agent-v0: partial batch (1-2 runs per scenario, 32/100 runs)

agent-v1: partial batch (3-4 runs per scenario, 64/100 runs)

## Step limit (all split, fault runs)

An agent that is still calling tools after 15 model turns is told to give its final answer. This splits each agent's fault runs by whether that happened: how many hit the limit, how many of those then answered "no incident", and the accuracy (mean over runs, not per scenario) with and without hitting it.

| solver | fault runs | hit the limit | then said no incident | accuracy when hit | accuracy otherwise |
|---|---|---|---|---|---|
| agent-v0 | 24 | 9 (38%) | 3 of 9 | 0.56 | 0.30 |
| agent-v1 | 51 | 32 (63%) | 19 of 32 | 0.28 | 0.63 |
| agent-v0-nemotron | 80 | 77 (96%) | 0 of 77 | 0.69 | 0.67 |
| agent-v1-nemotron | 80 | 57 (71%) | 2 of 57 | 0.61 | 0.83 |
| agent-v1-nemotron-nopriors | 80 | 53 (66%) | 0 of 53 | 0.62 | 0.76 |
| agent-v1-nemotron-vague | 80 | 64 (80%) | 3 of 64 | 0.51 | 0.75 |

## Cost

The heuristic makes no model calls, so it has no token usage.

| solver | runs with usage / records | requests (mean) | requests (max) | prompt tokens (mean) | completion tokens (mean) | tokens per correct run |
|---|---|---|---|---|---|---|
| heuristic | 0 / 20 | - | - | - | - | - |
| agent-v0 | 32 / 32 | 11.50 | 16 | 68442 | 660 | 126356 |
| agent-v1 | 64 / 64 | 14.12 | 16 | 75211 | 524 | 142560 |
| agent-v1-nopriors | not run | not run | not run | not run | not run | not run |
| agent-v1-vague | not run | not run | not run | not run | not run | not run |
| agent-v0-nemotron | 100 / 100 | 15.96 | 17 | 74265 | 3274 | 126080 |
| agent-v1-nemotron | 100 / 100 | 15.06 | 17 | 94309 | 3761 | 153234 |
| agent-v1-nemotron-nopriors | 100 / 100 | 14.85 | 17 | 89252 | 3534 | 146119 |
| agent-v1-nemotron-vague | 100 / 100 | 15.17 | 17 | 89947 | 3687 | 189160 |

## Per-scenario accuracy

`*` marks held-out scenarios; each cell is the mean over that scenario's runs, with the number of runs.

| scenario | category | heuristic | agent-v0 | agent-v1 | agent-v1-nopriors | agent-v1-vague | agent-v0-nemotron | agent-v1-nemotron | agent-v1-nemotron-nopriors | agent-v1-nemotron-vague |
|---|---|---|---|---|---|---|---|---|---|---|
| ad-failure | easy | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (4 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) |
| ad-high-cpu | hard-silent | 1.00 (1 run) | 0.00 (2 runs) | 0.00 (4 runs) | not run | not run | 0.00 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) | 0.00 (5 runs) |
| checkout-cpu-throttle | hard-silent | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (4 runs) | not run | not run | 0.60 (5 runs) | 0.80 (5 runs) | 0.80 (5 runs) | 1.00 (5 runs) |
| control-1 | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (4 runs) | not run | not run | 0.40 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) | 0.20 (5 runs) |
| control-2 | control | 0.00 (1 run) | 1.00 (2 runs) | 1.00 (3 runs) | not run | not run | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) |
| control-3 | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (3 runs) | not run | not run | 0.60 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) | 0.60 (5 runs) |
| control-4* | control | 1.00 (1 run) | 1.00 (2 runs) | 1.00 (3 runs) | not run | not run | 0.20 (5 runs) | 0.40 (5 runs) | 0.80 (5 runs) | 0.20 (5 runs) |
| email-memory-leak | hard-silent | 1.00 (1 run) | 0.00 (2 runs) | 0.67 (3 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 0.20 (5 runs) |
| image-slow-load-and-ad-high-cpu | hard-two-faults | 0.50 (1 run) | 0.00 (2 runs) | 0.17 (3 runs) | not run | not run | 0.40 (5 runs) | 0.50 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) |
| image-slow-load | hard-silent | 1.00 (1 run) | 0.50 (2 runs) | 0.33 (3 runs) | not run | not run | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) |
| kafka-queue-problems | hard-cross-service | 0.00 (1 run) | 0.00 (2 runs) | 0.00 (3 runs) | not run | not run | 0.40 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) | 0.00 (5 runs) |
| lock-contention-with-flood | hard-noisy | 0.00 (1 run) | 0.50 (2 runs) | 0.33 (3 runs) | not run | not run | 0.40 (5 runs) | 0.20 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) |
| payment-failure-50 | easy | 1.00 (1 run) | 0.00 (1 run) | 1.00 (3 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) |
| payment-failure-and-recommendation-leak* | hard-two-faults | 1.00 (1 run) | 0.50 (1 run) | 0.17 (3 runs) | not run | not run | 0.50 (5 runs) | 0.70 (5 runs) | 0.90 (5 runs) | 0.50 (5 runs) |
| payment-failure-with-flood* | hard-noisy | 1.00 (1 run) | 1.00 (1 run) | 1.00 (3 runs) | not run | not run | 1.00 (5 runs) | 1.00 (5 runs) | 0.80 (5 runs) | 1.00 (5 runs) |
| payment-unreachable | hard-cross-service | 0.00 (1 run) | 0.00 (1 run) | 0.00 (3 runs) | not run | not run | 0.80 (5 runs) | 0.60 (5 runs) | 0.60 (5 runs) | 0.40 (5 runs) |
| product-catalog-failure* | easy | 0.00 (1 run) | 1.00 (1 run) | 0.00 (3 runs) | not run | not run | 1.00 (5 runs) | 0.60 (5 runs) | 0.80 (5 runs) | 0.60 (5 runs) |
| product-catalog-lock-contention | hard-silent | 0.00 (1 run) | 1.00 (1 run) | 0.33 (3 runs) | not run | not run | 0.60 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) | 0.20 (5 runs) |
| recommendation-cache-leak* | hard-silent | 1.00 (1 run) | 0.00 (1 run) | 0.00 (3 runs) | not run | not run | 0.80 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) | 1.00 (5 runs) |
| valkey-cart-paused* | hard-cross-service | 0.00 (1 run) | 0.00 (1 run) | 0.33 (3 runs) | not run | not run | 0.80 (5 runs) | 0.40 (5 runs) | 0.20 (5 runs) | 0.40 (5 runs) |

## Accuracy vs coverage (all split, record-level)

![accuracy vs coverage](figures/coverage.png)

Coverage is the fraction of all runs whose answer is at or above the confidence threshold (abstentions never count). Accuracy here is over answered runs only, so the lowest-threshold point can exceed the tables' accuracy, which counts abstentions as wrong.

agent-v0: accuracy 0.71 at 59% coverage (the curve point nearest 50%, confidence >= 0.95). Partial batch (1-2 runs per scenario, 32/100 runs): treat with caution.

agent-v1: accuracy 0.67 at 52% coverage (the curve point nearest 50%, confidence >= 0.95). Partial batch (3-4 runs per scenario, 64/100 runs): treat with caution.

agent-v0-nemotron: accuracy 0.73 at 49% coverage (the curve point nearest 50%, confidence >= 0.90).

agent-v1-nemotron: accuracy 0.67 at 70% coverage (the curve point nearest 50%, confidence >= 0.90).

agent-v1-nemotron-nopriors: accuracy 0.60 at 31% coverage (the curve point nearest 50%, confidence >= 0.92).

agent-v1-nemotron-vague: accuracy 0.54 at 68% coverage (the curve point nearest 50%, confidence >= 0.90).

## Provenance

Code versions (git short sha) of the records behind each solver:

- heuristic: e53dd3d
- agent-v0: 23ebb5e
- agent-v1: 4626c77, 8705d39
- agent-v1-nopriors: not run
- agent-v1-vague: not run
- agent-v0-nemotron: cfa0c6e
- agent-v1-nemotron: 8b4fefb
- agent-v1-nemotron-nopriors: dc26375
- agent-v1-nemotron-vague: dc26375

During agent-v1 development, v1 tool output was viewed on one held-out incident (valkey-cart-paused). The one feature it suggested that no tuning snapshot exercised (an incomplete-services list) was removed before any v1 run; the other changes from that time (stopped service-map edges, the 'after = 0 can mean the service stopped reporting' caveat) are each exercised by the tuning snapshot payment-unreachable.

## Not run

Solvers with no recorded runs: agent-v1-nopriors, agent-v1-vague.

A Flash vs Flash-Lite comparison is absent: Flash's free tier allows 20 requests/day and one agent run takes about 12-15 requests (up to 17), so the Gemini agents run on `gemini-3.5-flash-lite` only. The model comparison is instead agent-v1-nemotron: agent v1 unchanged (prompt, tools, step limit) on `nvidia/nemotron-3-super-120b-a12b` through NVIDIA's free trial endpoint.

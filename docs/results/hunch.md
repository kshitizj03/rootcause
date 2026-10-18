# Hunch entry test: the second decision model

**It fails the bar too.** Zero-shot, both Hunch sizes answer "no incident" on all 20 snapshots. That gives 0 of 16 fault incidents right and 4 of 4 controls. The heuristic scores 0.59 on the fault incidents, so the bar fixed before the test is not met, and no decision-model-first cascade is built. This is the same outcome as the [Laya test](laya.md).

## What was tested

[Hunch](https://github.com/antareslabsorg/hunch) (Antares Labs, Apache-2.0, research preview) is a decision scorer: a fine-tuned Qwen3 backbone with a scalar readout. It returns a probability for every candidate answer and generates no text.

- **Same test as Laya:** the same inputs and the same "which service is the root cause, if any?" question, made from `experiments/laya/prepare.py`. Each snapshot's full change table is the state (no alert text). Every service is a candidate, plus `no_incident`. There is a second question for the fault type.
- **Scoring:** through `evaluate.run`, with the same rules as every other solver.
- **Variants:** two, declared before any result: **hunch-1.7b** (primary) and **hunch-0.6b**. Both ran zero-shot at temperature 1.0, as Hunch's README recommends for inputs unlike its training families.
- **Engine:** `FastHunch`, which reads each state once. The reference `Hunch` scores every candidate as its own path, so 20 candidates (19 services plus `no_incident`) over a ~3,200-token state needs about 64k padded tokens, more than its 32k budget.
- **Precision:** bf16, so the 1.7B fits a 6 GB GPU.

## Results

| | fault incidents (16) | top-3 | controls (4) |
|---|---|---|---|
| heuristic (the bar) | **0.59** | 0.75 | 0.75 |
| hunch-1.7b | 0.00 | 0.00 | 1.00 (always "no incident") |
| hunch-0.6b | 0.00 | 0.00 | 1.00 (always "no incident") |
| laya-multilingual, for comparison | 0.31 | 0.38 | 0.50 |

The probabilities barely change from one incident to the next:
- **1.7B:** `no_incident` gets 0.14-0.25 everywhere, and each service about 0.02-0.11.
- **0.6B:** the top three are almost the same on every snapshot (`no_incident` about 0.2, then frontend and cart).

The model is not reading the numbers. A single "nothing is wrong" option collects the probability that 19 near-identical service options split between them.

## Checking that this is the model, not the setup

All of these used the 0.6B, fp32 and bf16, in plain `Hunch` and `FastHunch`:

- **Setup check:** the README's own example ("I was charged twice for my order.") is routed to billing at 0.81-0.86 in every configuration. FastHunch in bf16 matches plain Hunch in fp32 to within about 0.01.
- **An obvious toy incident:** "payment error_ratio: 0.01 -> 0.35 (up, 33x)" next to a flat cart latency, with three options. It gives payment 0.47, cart 0.21 and no incident 0.32.
- **A calm toy table:** the same table with nothing changed still gives payment 0.39-0.40 against no incident 0.39-0.41. bf16 rounding is enough to flip which one wins.
- **Conclusion:** a 33x error-rate jump moves the answer by about 0.08. Hunch's own report says it is weakest on inputs unlike its training families (routing, intent, moderation, verification), and a numeric before/after table is far from those.

## Reproduce

Hunch needs Python 3.12 or newer, in its own venv (the runs here used Python 3.14, torch 2.14.1+cu130 and transformers 5.19.0):

```bash
python3.12 -m venv .cache/venv-hunch                                         # on Windows: py -3.12 -m venv .cache/venv-hunch
git clone https://github.com/antareslabsorg/hunch .cache/hunch-src
git -C .cache/hunch-src checkout 8d3dffb
.cache/venv-hunch/Scripts/python -m pip install -e .cache/hunch-src torch==2.14.1 transformers==5.19.0
```

For the GPU, install torch with CUDA from the PyTorch index, as in [laya.md](laya.md). Then:

```bash
.venv/Scripts/python -m experiments.laya.prepare                         # same inputs as Laya
HF_HOME=.cache/hf .cache/venv-hunch/Scripts/python -I experiments/hunch/predict.py
.venv/Scripts/python -m experiments.laya.score .cache/hunch/predictions.json
```

The paths are for Windows; on macOS/Linux use `bin/python` instead of `Scripts/python`. The `HF_HOME=... command` form is for bash; in PowerShell run `$env:HF_HOME = ".cache/hf"` first, then the command without the prefix.

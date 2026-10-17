"""Hunch entry test, step 2 of 3 (Hunch's own venv): the Laya entry test's inputs and questions, scored by Hunch.

Step 1 (inputs) and step 3 (scoring) are the Laya scripts, run with the project's python:
    python -m experiments.laya.prepare
    <hunch venv python> -I experiments/hunch/predict.py      (with HF_HOME set to a local cache path, e.g. .cache/hf)
    python -m experiments.laya.score .cache/hunch/predictions.json
Hunch's venv is separate: torch plus an install of https://github.com/antareslabsorg/hunch (commit 8d3dffb was used);
its package is antareslabs-hunch, not the unrelated `hunch` on PyPI. The checkpoints are pinned to the revisions scored.

Two variants, fixed before any result was seen: hunch-1.7b (primary) and hunch-0.6b, both on the full change table,
zero-shot, with temperature 1.0 (Hunch's README: use T = 1.0 for inputs unlike its training families).
Both run in bf16 (the 1.7B needs it to fit a 6 GB GPU); Hunch reports bf16 changes 28 of its 6,000 held-out answers vs fp32.
"""
import json
import time
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from hunch.fast import FastHunch

ROOT = Path(__file__).resolve().parents[2]
IN, OUT = ROOT / ".cache" / "laya" / "inputs.json", ROOT / ".cache" / "hunch" / "predictions.json"
# (Hunch checkpoint, its revision, base model, its revision): the revisions the recorded results used, so a re-run
# scores the same weights even after the preview repositories move on
VARIANTS = {"hunch-1.7b": ("antareslabs/hunch-1.7b-preview", "5ec616dfe2eb0b01842bc28a14ee67af46a1c26c",
                           "Qwen/Qwen3-1.7B", "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"),
            "hunch-0.6b": ("antareslabs/hunch-0.6b-preview", "193347989316e6d77ecb6fc46018eacc3b103e60",
                           "Qwen/Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca")}
FAULT = {"id": "fault_type", "type": "choice", "instruction": "What kind of fault is it?",
         "candidates": [{"id": "errors", "label": "Errors", "description": "requests fail or return errors"},
                        {"id": "latency", "label": "Latency", "description": "requests become slow"},
                        {"id": "resource", "label": "Resource", "description": "CPU, memory or restarts of a service"}]}


def request(it):
    cands = [{"id": s, "label": s, "description": f"the fault is in the {s} service"} for s in it["services"]]
    cands.append({"id": "no_incident", "label": "No incident", "description": "nothing is broken; every change is normal variation"})
    return {"id": str(it["key"]), "state": {"change_table": it["full"]},
            "questions": [{"id": "cause", "type": "choice", "candidates": cands,
                           "instruction": "Which service is the root cause of the incident, if any?"}, FAULT]}


def load(repo, rev, base, base_rev):
    # FastHunch reads the state once per request; plain Hunch scores 21 copies of a ~2.7k-token state and overflows
    # its token budget. Same answers up to rounding (Hunch's scripts/check_fast.py). Hunch.load builds fp32 weights.
    h = FastHunch.load(snapshot_download(repo, revision=rev), model=snapshot_download(base, revision=base_rev), device="cpu")
    h.scorer.to(torch.bfloat16).to("cuda")
    h.device, h.amp_dtype, h.T = torch.device("cuda"), torch.bfloat16, 1.0
    return h


def main():
    items, out = json.loads(IN.read_text(encoding="utf-8")), {}
    for name, spec in VARIANTS.items():
        h, out[name] = load(*spec), {}
        for it in items:
            t = time.time()
            res = h.decide([request(it)])
            a = res["results"][0]["answers"]
            # Hunch never truncates its input: an over-long state raises, and an over-budget one runs unpacked
            out[name][str(it["key"])] = {"cause": a["cause"]["probabilities"], "fault_type": a["fault_type"]["choice"],
                                         "truncated": False, "seconds": round(time.time() - t, 2),
                                         "tokens": res["usage"]["path_tokens"]}
        print(name, "done", flush=True)
        del h
        torch.cuda.empty_cache()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()

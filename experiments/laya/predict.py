"""Laya entry test, step 2 of 3 (Laya's own venv, which has only laya + torch): answer two typed questions per snapshot.

Two variants, both fixed before any result was seen:
  laya-multilingual  the full change table, laya-multilingual with max_len=8192 (the primary test)
  laya-english       the top 20 rows, the English checkpoint (truncates at 1,024 input tokens, questions included,
                     as usage.input_tokens showed)
Zero-shot: no fine-tuning, no temperature fitting, nothing learned from these incidents.

    <laya venv python> -I experiments/laya/predict.py      (with HF_HOME set to a local cache path, e.g. .cache/hf)
Laya's venv is separate: torch plus laya 0.4.6 from PyPI.
"""
import json
import time
from pathlib import Path

from laya import Router

ROOT = Path(__file__).resolve().parents[2]
IN, OUT = ROOT / ".cache" / "laya" / "inputs.json", ROOT / ".cache" / "laya" / "predictions.json"
VARIANTS = {"laya-multilingual": ("full", {"model": "multilingual", "max_len": 8192}),
            "laya-english": ("top", {"model": "english"})}
FAULT = {"type": "choice", "instructions": "What kind of fault is it?",
         "criteria": {"errors": "requests fail or return errors",
                      "latency": "requests become slow",
                      "resource": "CPU, memory or restarts of a service"}}


def questions(services):
    criteria = {s: f"the fault is in the {s} service" for s in services}
    criteria["no_incident"] = "nothing is broken; every change is normal variation"
    return {"cause": {"type": "choice", "criteria": criteria,
                      "instructions": "Which service is the root cause of the incident, if any?"},
            "fault_type": FAULT}


def main():
    items, router, out = json.loads(IN.read_text(encoding="utf-8")), Router(), {}
    for name, (field, kw) in VARIANTS.items():
        out[name] = {}
        for it in items:
            t = time.time()
            res = router.predict(it[field], questions(it["services"]), **kw)
            a = res["answers"]
            out[name][str(it["key"])] = {"cause": a["cause"]["probabilities"], "fault_type": a["fault_type"]["choice"],
                                         "truncated": res["usage"]["truncated"], "seconds": round(time.time() - t, 2),
                                         "tokens": res["usage"]["input_tokens"]}
        print(name, "done")
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("->", OUT)


if __name__ == "__main__":
    main()

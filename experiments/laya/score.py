"""Laya and Hunch entry tests, step 3 of 3 (project venv): turn either model's answers into reports and score them
like any solver.

Records go to data/runs/<variant>/ through evaluate.run, so the scoring rules, truth handling and code tag are the
same as every other solver's. A report ranks services by the model's probability (top 3); `no_incident` wins only if
it is the single most likely option. Neither model cites evidence, so their reports carry none.

    python -m experiments.laya.score [predictions.json]   (default: Laya's; Hunch's are in
    .cache/hunch/predictions.json)
"""
import json
import sys
from pathlib import Path

from rootcause import config, evaluate
from rootcause.score import Cause, Report

PRED = config.ROOT / ".cache" / "laya" / "predictions.json"


def report(p):
    ranked = sorted(p["cause"].items(), key=lambda kv: -kv[1])
    if ranked[0][0] == "no_incident":
        return Report("no_incident", (), (), ranked[0][1])
    causes = tuple(Cause(s, p["fault_type"]) for s, _ in ranked if s != "no_incident")[:3]
    return Report("incident", causes, (), ranked[0][1])


def main():
    preds = json.loads((Path(sys.argv[1]) if len(sys.argv) > 1 else PRED).read_text(encoding="utf-8"))
    for name, by_key in preds.items():
        def solve(snap, by_key=by_key, name=name):
            p = by_key[str(snap["meta"]["fault_start"])]
            return report(p), {"solver": name, "truncated": p["truncated"], "input_tokens": p["tokens"],
                               "model_seconds": p["seconds"]}
        out = evaluate.run(name, solve, runs=1)
        print(name, out)
        print(evaluate.format_summary(evaluate.summarise(name, expected=evaluate.expected_counts("all"))))


if __name__ == "__main__":
    main()

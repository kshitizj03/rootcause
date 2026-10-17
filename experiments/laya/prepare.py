"""Laya entry test, step 1 of 3 (project venv): write each snapshot's compressed change table as Laya inputs.

The table is the heuristic's own input (summary.changes: every service's signals, baseline window vs fault window,
ranked by relative change). No alert text, no ground truth. Keyed by the snapshot's fault_start, which is what
score.py sees again through evaluate.run.

    .venv/Scripts/python.exe -m experiments.laya.prepare
"""
import json

from rootcause import config, evaluate, snapshot, summary

OUT = config.ROOT / ".cache" / "laya" / "inputs.json"
TOP = 20  # rows given to the English checkpoint, which truncates at 1,024 input tokens, questions included


def _num(x):
    return f"{x:.3g}"


def table(rows):
    lines = [f"{r['service']} {r['signal']}: {_num(r['baseline'])} -> {_num(r['value'])} "
             f"({r['direction']}, change {r['score']:.1f}x)" for r in rows]
    return ("Microservice signals in the 15 minutes before an alert vs the minutes after it, "
            "largest relative change first:\n" + "\n".join(lines))


def main():
    items = []
    for _, _, path in evaluate.targets():  # the snapshots evaluate.run scores
        snap = snapshot.load(path)
        rows = summary.changes(snap)
        items.append({"key": snap["meta"]["fault_start"], "services": sorted({r["service"] for r in rows}),
                      "full": table(rows), "top": table(rows[:TOP])})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, indent=1), encoding="utf-8")
    print(f"{len(items)} snapshots -> {OUT}")


if __name__ == "__main__":
    main()

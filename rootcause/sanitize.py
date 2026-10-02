"""Remove anything that reveals the injected fault before telemetry is stored or shown to an agent."""
import gzip
import json
import re
from pathlib import Path

from rootcause import config

PHRASES = [r"feature[\s_\-]?flags?", r"flagd", r"openfeature"]
SNAPSHOT_TOOL_FILES = ("metrics.json", "spans.jsonl.gz", "logs.jsonl.gz")  # what agent tools can read


def flag_names(flags_file=config.FLAGS_FILE):
    return sorted(json.loads(Path(flags_file).read_text())["flags"])


def leak_pattern(names):
    return re.compile("|".join([re.escape(n) for n in names] + PHRASES), re.IGNORECASE)


def _redact(obj, pat):
    return json.loads(pat.sub("[redacted]", json.dumps(obj)))


def sanitize_spans(spans, names):
    pat = leak_pattern(names)
    kept = []
    for sp in spans:
        if sp["service"] in config.HIDDEN_SERVICES:
            continue
        attrs = {k: v for k, v in sp["attributes"].items() if not k.startswith("feature_flag")}
        # ponytail: drops whole spans that call the flag service; their children lose a parent, fine for diagnosis
        if any(pat.search(str(v)) for v in attrs.values()):
            continue
        events = [e for e in sp["events"] if not e["name"].startswith("feature_flag")]
        kept.append(_redact(dict(sp, attributes=attrs, events=events), pat))
    return kept


def sanitize_logs(logs, names):
    pat = leak_pattern(names)
    return [_redact(lg, pat) for lg in logs if lg["service"] not in config.HIDDEN_SERVICES]


def find_leaks(text, names):
    return sorted({m.group(0).lower() for m in leak_pattern(names).finditer(text)})


def scan_snapshot(path, names):
    path, found = Path(path), {}
    for name in SNAPSHOT_TOOL_FILES:
        p = path / name
        if not p.exists():
            continue
        if name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                text = f.read()
        else:
            text = p.read_text(encoding="utf-8")
        hits = find_leaks(text, names)
        if hits:
            found[name] = hits
    return found

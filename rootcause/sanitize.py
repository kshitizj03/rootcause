"""Remove anything that reveals the injected fault before telemetry is stored or shown to an agent."""
import gzip
import json
import re
from pathlib import Path

from rootcause import config

PHRASES = [r"feature[\s_\-.]?flags?", r"flagd", r"openfeature", r"ofrep", r"flagservice", r"\[redacted\]",  # stubs left by older snapshots
           # demo services that announce the injected fault in their own telemetry; deliberately narrow so generic
           # "lock wait timeout" / "server overloaded" / "lock contention" wording from real systems stays.
           r"\bproblempattern\b", r"overload simulation", r"\block contention (?:scenario|transaction)\b"]
SNAPSHOT_TOOL_FILES = ("metrics.json", "spans.jsonl.gz", "logs.jsonl.gz")  # what agent tools can read


def flag_names(flags_file=config.FLAGS_FILE):
    return sorted(json.loads(Path(flags_file).read_text(encoding="utf-8"))["flags"])


def leak_pattern(names):
    # Convert camelCase flag names to separator-tolerant patterns
    sep_names = []
    for n in names:
        # Split camelCase: "kafkaQueueProblems" -> ["kafka", "Queue", "Problems"]
        words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", n)
        if words:
            # Join with optional separators (no space): kafka[_\-.]?queue[_\-.]?problems
            pattern = r"[_\-.]?".join(re.escape(w) for w in words)
            sep_names.append(pattern)
        else:
            sep_names.append(re.escape(n))
    return re.compile("|".join(sep_names + PHRASES), re.IGNORECASE)


# Benign strings that would otherwise trip the leak pattern; rewritten (not dropped) before the key-strip and drop test.
NEUTRAL_REWRITES = [
    # vendor src/product-catalog/main.go:397 (demo self-reports the flag; a real service says a plain error). Exact demo string,
    # so case-sensitive; "[redacted]" is the stub older snapshots hold.
    (re.compile(r"Product Catalog Fail (?:Feature Flag|\[redacted\]) Enabled"), "Product Catalog Fail"),
]


def _rewrite(obj):
    if isinstance(obj, str):
        for rx, repl in NEUTRAL_REWRITES:
            obj = rx.sub(repl, obj)
        return obj
    if isinstance(obj, list):
        return [_rewrite(v) for v in obj]
    if isinstance(obj, dict):
        return {_rewrite(k): _rewrite(v) for k, v in obj.items()}
    return obj


def _strip_keys(obj, pat):
    """Remove every dict entry whose KEY matches. Booleans carry no flag name, so a leaky key must go with its value."""
    if isinstance(obj, list):
        return [_strip_keys(v, pat) for v in obj]
    if isinstance(obj, dict):
        return {k: _strip_keys(v, pat) for k, v in obj.items() if not (isinstance(k, str) and pat.search(k))}
    return obj


def _matches(obj, pat):
    if isinstance(obj, str):
        return bool(pat.search(obj))
    if isinstance(obj, list):
        return any(_matches(v, pat) for v in obj)
    if isinstance(obj, dict):
        return any(_matches(k, pat) or _matches(v, pat) for k, v in obj.items())
    return False


def sanitize_spans(spans, names):
    pat = leak_pattern(names)
    kept = []
    for sp in spans:
        if sp["service"].lower() in config.HIDDEN_SERVICES:
            continue
        sp = _rewrite(sp)
        attrs = {k: v for k, v in sp["attributes"].items() if not k.startswith("feature_flag")}
        events = [e for e in sp["events"] if not e["name"].startswith("feature_flag")]
        sp = _strip_keys(dict(sp, attributes=attrs, events=events), pat)
        # ponytail: drops whole spans whose remaining content matches; their children lose a parent, fine for diagnosis
        if _matches(sp, pat):
            continue
        kept.append(sp)
    return kept


def sanitize_logs(logs, names):
    pat = leak_pattern(names)
    # drop (not redact) matching records: a "[redacted]" stub still hints that a flag was named.
    stripped = (_strip_keys(_rewrite(lg), pat) for lg in logs if lg["service"].lower() not in config.HIDDEN_SERVICES)
    return [lg for lg in stripped if not _matches(lg, pat)]


def sanitize_metrics(metrics):
    """{signal: {service: points}} -> only series of services the agent may see (drops hidden and unknown keys)."""
    return {sig: {k: v for k, v in by_service.items() if k in config.KNOWN_TARGETS} for sig, by_service in metrics.items()}


def find_leaks(text, names):
    return sorted({m.group(0).lower() for m in leak_pattern(names).finditer(text)})


def scan_snapshot(path, names):
    path, found = Path(path), {}
    for name in SNAPSHOT_TOOL_FILES:
        p = path / name
        if not p.exists():
            raise FileNotFoundError(f"Required snapshot file missing: {name}")
        if name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                text = f.read()
        else:
            text = p.read_text(encoding="utf-8")
        hits = find_leaks(text, names)
        if name == "metrics.json":
            services = {k for by_service in json.loads(text).values() for k in by_service}
        else:
            services = {str(json.loads(l).get("service", "")).lower() for l in text.splitlines() if l.strip()}
        hits += [f"hidden service: {k}" for k in sorted(services & config.HIDDEN_SERVICES)]
        if hits:
            found[name] = hits
    return found

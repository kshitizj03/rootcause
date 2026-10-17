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
# TOOL BOUNDARY: agent tools may read ONLY meta.json plus these files. validation.json, truth.json, index.jsonl and the
# repository (scenarios/, including scenarios/NOTES.md) name the answer and must never be exposed to an agent.
SNAPSHOT_TOOL_FILES = ("metrics.json", "spans.jsonl.gz", "logs.jsonl.gz")  # what agent tools can read (besides meta.json)


def flag_names(flags_file=config.FLAGS_FILE):
    return sorted(json.loads(Path(flags_file).read_text(encoding="utf-8"))["flags"])


def flag_words(name):
    """Split a camelCase flag name: "kafkaQueueProblems" -> ["kafka", "Queue", "Problems"]."""
    return re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", name)


# A flag name must start a word: after a non-alphanumeric, or at a camelCase hump (isAdFailure), never inside a word
# ("readFailure", "upload_failure" hold "adfailure" but name no flag). Case-sensitive, inside the case-blind pattern.
_WORD_START = r"(?-i:(?<![A-Za-z0-9])|(?<=[a-z0-9])(?=[A-Z]))"


def leak_pattern(names):
    # camelCase flag names as separator-tolerant patterns (no space): kafka[_\-.]?queue[_\-.]?problems
    sep_names = [_WORD_START + (r"[_\-.]?".join(re.escape(w) for w in words) if (words := flag_words(n)) else re.escape(n))
                 for n in names]
    return re.compile("|".join(sep_names + PHRASES), re.IGNORECASE)


# Benign strings that would otherwise trip the leak pattern; rewritten (not dropped) before the key-strip and drop test.
NEUTRAL_REWRITES = [
    # upstream open-telemetry/opentelemetry-demo src/product-catalog/main.go (the demo self-reports the flag; a real
    # service says a plain error). Exact demo string, so case-sensitive; "[redacted]" is the stub older snapshots hold.
    (re.compile(r"Product Catalog Fail (?:Feature Flag|\[redacted\]) Enabled"), "Product Catalog Fail"),
]

# Envoy's fault filter marks injected delays/aborts with DI/FI in RESPONSE_FLAGS ("delay injected"): the answer for
# image-slow-load. Rewritten, not dropped, so the latency evidence survives. Access-log form: `" 200 DI via_upstream`.
FAULT_FLAGS = {"DI", "FI"}
_ACCESS_FLAGS = re.compile(r'(" \d{1,3} )([A-Z]+(?:,[A-Z]+)*)(?= )')


def _drop_fault_flags(flags):
    return ",".join(f for f in flags.split(",") if f not in FAULT_FLAGS) or "-"


NEUTRAL_REWRITES.append((_ACCESS_FLAGS, lambda m: m.group(1) + _drop_fault_flags(m.group(2))))


def _is_flags_key(k):
    return isinstance(k, str) and (k == "response_flags" or k.endswith(".response_flags"))


def _has_fault_flag(obj):
    """True if obj still holds an Envoy DI/FI flag, in a response_flags value or an access-log flags field."""
    if isinstance(obj, str):
        return any(set(m.group(2).split(",")) & FAULT_FLAGS for m in _ACCESS_FLAGS.finditer(obj))
    if isinstance(obj, list):
        return any(_has_fault_flag(v) for v in obj)
    if isinstance(obj, dict):
        return any(bool(set(v.split(",")) & FAULT_FLAGS) if _is_flags_key(k) and isinstance(v, str) else _has_fault_flag(v)
                   for k, v in obj.items())
    return False


def _rewrite(obj):
    if isinstance(obj, str):
        for rx, repl in NEUTRAL_REWRITES:
            obj = rx.sub(repl, obj)
        return obj
    if isinstance(obj, list):
        return [_rewrite(v) for v in obj]
    if isinstance(obj, dict):
        return {_rewrite(k): _drop_fault_flags(v) if _is_flags_key(k) and isinstance(v, str) else _rewrite(v)
                for k, v in obj.items()}
    return obj


def _strip_keys(obj, pat):
    """Remove every dict entry whose KEY matches. Booleans carry no flag name, so a leaky key must go with its value."""
    if isinstance(obj, list):
        return [_strip_keys(v, pat) for v in obj]
    if isinstance(obj, dict):
        return {k: _strip_keys(v, pat) for k, v in obj.items() if not (isinstance(k, str) and pat.search(k))}
    return obj


def _strings(obj):
    """Every string in obj, dict keys included."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)


def _matches(obj, pat):
    return any(pat.search(s) for s in _strings(obj))


def _leaks(obj, names):
    """find_leaks over the decoded strings of obj (not its JSON text, where a form feed written as \\f reads as an "f")."""
    pat = leak_pattern(names)
    return sorted({m.group(0).lower() for s in _strings(obj) for m in pat.finditer(s)})


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
        # Drops whole spans whose remaining content matches; their children lose a parent, which is fine for diagnosis.
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
    meta = path / "meta.json"  # agents read its alert too
    if meta.exists() and (hits := find_leaks(str(json.loads(meta.read_text(encoding="utf-8")).get("alert", "")), names)):
        found["meta.json"] = hits
    for name in SNAPSHOT_TOOL_FILES:
        p = path / name
        if not p.exists():
            raise FileNotFoundError(f"Required snapshot file missing: {name}")
        if name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rows = [json.loads(l) for l in f if l.strip()]
            hits = _leaks(rows, names)  # the decoded values, as the sanitiser matched them
            services = {str(r.get("service", "")).lower() for r in rows}
            if any(_has_fault_flag(r) for r in rows):  # scan-only: the sanitiser rewrites these, never drops
                hits.append("fault-injection flag")
        else:
            metrics = json.loads(p.read_text(encoding="utf-8"))
            hits = _leaks(metrics, names)
            services = {k for by_service in metrics.values() for k in by_service}
        hits += [f"hidden service: {k}" for k in sorted(services & config.HIDDEN_SERVICES)]
        if hits:
            found[name] = hits
    return found

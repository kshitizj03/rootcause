import json
import random

from helpers import flat_log, flat_span, series, write_snapshot
from rootcause import snapshot, tools_v1

# well-typed but extreme values for each parameter kind: a tool must answer them itself, never through call()'s
# catch-all "bad call" path, which exists for malformed input and would hide a bug in the tool
VALUES = {
    "service": ["payment", "PAYMENT", " payment ", "nope", "", "支付", "a" * 300],
    "signal": ["error_ratio", "p95_ms", "mem_mb", "cpu_cores", "rps", "uptime_s", "nope", ""],
    "trace_id": ["t1", "nope", "", "0" * 64],
    "text": ["charge", "", "%", ".*", "\\", "x" * 500],
    "errors_only": [True, False, "true", "no", 1, 0],
    "include_load": [True, False, "yes", "1", 0],
    "limit": [-5, 0, 1, 3, 10 ** 9, 2.5, "7"],
    "n": [-1, 0, 2, 10 ** 9, "4"],
    "min_severity": [-1, 0, 9, 17, 1000, "13"],
    "since": [-10 ** 7, -900, -60, 0, 60, 10 ** 7, None],
    "until": [-10 ** 7, -60, 0, 60, 300, 10 ** 7, None],
}


def test_well_typed_extreme_arguments_never_reach_the_catch_all(tmp_path):
    spans = [flat_span(span_id=f"s{i}", error=i % 3 == 0, message="boom" if i % 3 == 0 else "") for i in range(30)]
    logs = [flat_log("payment", f"charge failed {i}", ts=f"1970-01-01T00:{10 + i // 6:02d}:{i % 6 * 10:02d}") for i in range(30)]
    path = write_snapshot(tmp_path / "incident__x", spans=spans, logs=logs,
                          metrics={"error_ratio": {"payment": series(0.0, 0.3)}, "p95_ms": {"cart": series(2.0, 9000.0)}})
    snap = snapshot.load(path)
    params = {s["function"]["name"]: list(s["function"]["parameters"].get("properties", {})) for s in tools_v1.SCHEMAS}
    required = {s["function"]["name"]: set(s["function"]["parameters"].get("required", [])) for s in tools_v1.SCHEMAS}
    rng = random.Random(0)
    for _ in range(600):
        name = rng.choice(sorted(params))
        args = {p: rng.choice(VALUES[p]) for p in params[name] if p in required[name] or rng.random() < 0.8}
        text = tools_v1.call(snap, name, json.dumps(args))
        out = json.loads(text)  # always valid JSON (outputs here stay under the size cap)
        assert not (isinstance(out, dict) and str(out.get("error", "")).startswith("bad call")), (name, args, out)

"""Thin HTTP clients for Prometheus, Jaeger (v3 API) and OpenSearch, plus pure flatteners."""
from datetime import datetime, timezone

import requests

from rootcause import config


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prom_range(query, start, end, step=config.STEP_S):
    r = requests.get(f"{config.PROM}/api/v1/query_range",
                     params={"query": query, "start": start, "end": end, "step": step}, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["result"]


def jaeger_services():
    r = requests.get(f"{config.JAEGER}/services", timeout=20)
    r.raise_for_status()
    return r.json().get("services", [])


def jaeger_raw(service, start, end, limit):
    params = {"query.service_name": service, "query.num_traces": limit,
              "query.start_time_min": _iso(start), "query.start_time_max": _iso(end)}
    r = requests.get(f"{config.JAEGER}/traces", params=params, timeout=120)
    if r.status_code == 404:  # the v3 API answers 404 when nothing matches
        return {"result": {"resourceSpans": []}}
    r.raise_for_status()
    return r.json()


def _value(v):
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    return str(v)


def _attrs(kvs):
    return {kv["key"]: _value(kv.get("value", {})) for kv in kvs}


def flatten_otlp(payload):
    """OTLP JSON (Jaeger v3) -> flat span dicts with plain attribute values."""
    out = []
    for rs in payload.get("result", {}).get("resourceSpans", []):
        service = _attrs(rs.get("resource", {}).get("attributes", [])).get("service.name", "?")
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                status = sp.get("status", {})
                start, end = int(sp["startTimeUnixNano"]), int(sp["endTimeUnixNano"])
                out.append({
                    "trace_id": sp["traceId"], "span_id": sp["spanId"], "parent_id": sp.get("parentSpanId", ""),
                    "service": service, "name": sp["name"], "start_ms": start / 1e6, "dur_ms": (end - start) / 1e6,
                    "error": status.get("code") in (2, "STATUS_CODE_ERROR"), "message": status.get("message", ""),
                    "attributes": _attrs(sp.get("attributes", [])),
                    "events": [{"name": e.get("name", ""), "attributes": _attrs(e.get("attributes", []))}
                               for e in sp.get("events", [])],
                })
    return out


def os_logs(query, start, end, size):
    body = {"size": size, "sort": [{"@timestamp": "desc"}],
            "query": {"bool": {"must": [{"query_string": {"query": query}}],
                               "filter": [{"range": {"@timestamp": {"gte": int(start * 1000), "lte": int(end * 1000),
                                                                    "format": "epoch_millis"}}}]}}}
    r = requests.post(f"{config.OPENSEARCH}/otel-logs-*/_search", json=body, timeout=60)
    r.raise_for_status()
    return [h["_source"] for h in r.json()["hits"]["hits"]]


def flatten_log(src):
    res = src.get("resource") or {}
    service = res.get("service.name") or (res.get("service") or {}).get("name") or "?"
    sev = src.get("severity") or {}
    return {"ts": src.get("@timestamp"), "service": service, "severity": sev.get("text"),
            "severity_number": sev.get("number"), "body": str(src.get("body") or ""), "trace_id": src.get("traceId", "")}

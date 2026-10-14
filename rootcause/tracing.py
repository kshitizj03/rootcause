"""Self-tracing for the agent: OpenTelemetry spans exported over OTLP/HTTP or to a JSONL file. Off unless asked for.
The agent only ever puts names, models, token and request counts, the verdict and error types on spans (never prompts
or tool arguments/outputs)."""
from pathlib import Path

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

from rootcause import config

OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
FILE_PATH = config.DATA / "agent_traces.jsonl"


class _JsonlExporter(SpanExporter):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans):
        with self.path.open("a", encoding="utf-8") as f:
            for s in spans:
                f.write(s.to_json(indent=None) + "\n")
        return SpanExportResult.SUCCESS


def setup(mode, path=None, endpoint=OTLP_ENDPOINT, set_global=True):
    """off -> None (nothing changes); otlp / file -> a TracerProvider (installed globally unless set_global=False)."""
    if mode == "off":
        return None
    if mode == "otlp":
        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=2)  # a dead endpoint only loses spans
    elif mode == "file":
        exporter = _JsonlExporter(path or FILE_PATH)
    else:
        raise ValueError(f"unknown trace mode {mode!r}")
    provider = TracerProvider(resource=Resource.create({"service.name": "rootcause-agent"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    if set_global:
        trace.set_tracer_provider(provider)
    return provider

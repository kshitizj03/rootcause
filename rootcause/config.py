"""Project-wide settings: paths, endpoints, demo compose files, service lists, timing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "vendor" / "opentelemetry-demo"
FLAGS_FILE = DEMO / "src" / "flagd" / "demo.flagd.json"
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
STATE_FILE = DATA / "state.json"
SCENARIOS_DIR = ROOT / "scenarios"

COMPOSE_FILES = ["compose.yaml", "compose.full.yaml", "compose.observability.yaml",
                 "compose.extras.yaml", str(ROOT / "infra" / "compose.ports.yaml")]

PROM = "http://localhost:9090"
JAEGER = "http://localhost:16686/jaeger/ui/api/v3"  # Jaeger v2 serves only the v3 API
OPENSEARCH = "http://localhost:9200"

# Services whose telemetry the agent may see (traced apps).
APP_SERVICES = ["accounting", "ad", "cart", "checkout", "currency", "email", "fraud-detection",
                "frontend", "frontend-proxy", "frontend-web", "image-provider", "load-generator",
                "payment", "product-catalog", "quote", "recommendation", "shipping"]
# The flag service would reveal the injected fault: never shown.
HIDDEN_SERVICES = {"flagd", "flagd-ui"}
# Untraced dependencies that still have container metrics and can be a root cause.
INFRA_CONTAINERS = ["kafka", "valkey-cart", "astronomy-db"]
KNOWN_TARGETS = APP_SERVICES + INFRA_CONTAINERS

COOLDOWN_S = 18 * 60        # the 15-minute baseline before an injection must be fault-free
BASELINE_S = 15 * 60
SETTLE_S = 180              # fault runs this long before capture
INGEST_LAG_S = 60           # metrics pushed ~once a minute; wait before capture to get last minute
RAMP_S = 60                 # skip the first minute of the fault when judging its signal
STEP_S = 15                 # metric resolution in snapshots
CAPTURE_LOOKBACK_S = 300    # spans/logs captured from 5 minutes before injection
TRACES_PER_SERVICE = 50
LOGS_PER_SERVICE = 200

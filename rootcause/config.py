"""Project-wide settings: paths, endpoints, demo compose files, service lists, timing."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "vendor" / "opentelemetry-demo"
FLAGS_FILE = DEMO / "src" / "flagd" / "demo.flagd.json"
DATA = ROOT / "data"
SNAPSHOTS = DATA / "snapshots"
STATE_FILE = DATA / "state.json"
SCENARIOS_DIR = ROOT / "scenarios"
# SHA-256 of the data release archive that fetch-data accepts: a placeholder until the data-v1 release is cut, then the
# digest `rootcause pack-data` prints for the published archive
DATA_SHA256 = "unset: filled in when the data-v1 release is cut"

COMPOSE_FILES = ["compose.yaml", "compose.full.yaml", "compose.observability.yaml",
                 "compose.extras.yaml", str(ROOT / "infra" / "compose.ports.yaml")]

PROM = "http://localhost:9090"
JAEGER = "http://localhost:16686/jaeger/ui/api/v3"  # the v3 API returns OTLP-shaped JSON, which backends.flatten_otlp parses
OPENSEARCH = "http://localhost:9200"

# Services whose telemetry the agent may see (traced apps).
APP_SERVICES = ["accounting", "ad", "cart", "checkout", "currency", "email", "fraud-detection",
                "frontend", "frontend-proxy", "frontend-web", "image-provider",
                "payment", "product-catalog", "quote", "recommendation", "shipping"]
# Never shown: flagd would reveal the injected fault; load-generator is the demo's synthetic users (not observable
# in production) and its flood task names (user_flood_home) reveal that a traffic surge is an artificial decoy.
HIDDEN_SERVICES = {"flagd", "flagd-ui", "load-generator"}
# Untraced dependencies that still have container metrics and can be a root cause.
INFRA_CONTAINERS = ["kafka", "valkey-cart", "astronomy-db"]
KNOWN_TARGETS = APP_SERVICES + INFRA_CONTAINERS

COOLDOWN_S = 18 * 60        # the 15-minute baseline before an injection must be fault-free
BASELINE_S = 15 * 60
SETTLE_S = 300              # fault runs this long before capture
INGEST_LAG_S = 60           # metrics pushed ~once a minute; wait before capture to get last minute
RAMP_S = 60                 # skip the first minute of the fault when judging its signal
EDGE_TOLERANCE_S = 1.0      # points this close past a window end still count (float error at the edge)
STEP_S = 15                 # metric resolution in snapshots
CAPTURE_LOOKBACK_S = 300    # spans/logs captured from 5 minutes before injection
TRACES_PER_SERVICE = 50
LOGS_PER_SERVICE = 200

# Frozen 2026-10-13, before any agent-v1 tuning: the alphabetically last scenario of each category; reported separately
# from the rest (the tuning set). Not used to tune prompts or tools, except that v1 tool output was viewed on
# valkey-cart-paused once during agent-v1 development (report.DISCLOSURE says what was kept).
HELDOUT = ("product-catalog-failure", "valkey-cart-paused", "recommendation-cache-leak",
           "payment-failure-with-flood", "payment-failure-and-recommendation-leak", "control-4")
HELDOUT_VIEWED = "valkey-cart-paused"  # the one held-out incident whose v1 tool output was viewed (report.DISCLOSURE)

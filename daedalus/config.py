"""Single source of config. PROJECT_NAME is the one rename point.

Reads a local .env if present (no python-dotenv dependency for a 6-line parser),
then exposes typed accessors. Nothing here calls the network.
"""

import os
from pathlib import Path

PROJECT_NAME = "daedalus"

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


def _env(key, default=""):
    return os.environ.get(key, default)


# storage
DATA_DIR = Path(_env("DAEDALUS_DIR", str(ROOT / "data")))
DB_PATH = Path(_env("DAEDALUS_DB", str(DATA_DIR / f"{PROJECT_NAME}.db")))
AUDIT_LOG_PATH = Path(_env("DAEDALUS_AUDIT_LOG", str(DATA_DIR / "spend_decisions.log")))
ORDER_STORE_PATH = Path(_env("DAEDALUS_ORDERS", str(DATA_DIR / "orders.json")))

# spend authorization: attended = one human tap (approval token required),
# policy = standing per-period limit, no tap under the cap.
APPROVAL_MODE = _env("APPROVAL_MODE", "attended")
POLICY_SPEND_LIMIT_CENTS = int(_env("POLICY_SPEND_LIMIT_CENTS", "1000"))

# Stripe (TEST MODE ONLY for this project). The `stripe` lib is optional: the
# plugin loads without it and runs Stripe paths as labelled stubs.
try:
    import stripe as _stripe_probe  # noqa: F401
    STRIPE_LIB = True
except ModuleNotFoundError:
    STRIPE_LIB = False
STRIPE_SECRET_KEY = _env("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = _env("STRIPE_WEBHOOK_SECRET")
STRIPE_TEST_MODE = STRIPE_SECRET_KEY.startswith("sk_test_") and STRIPE_LIB
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY) and STRIPE_LIB

# Nemotron via OpenRouter, with an optional local route for sensitive inference
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = _env("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
LOCAL_NEMOTRON_URL = _env("LOCAL_NEMOTRON_URL")
LOCAL_NEMOTRON_MODEL = _env("LOCAL_NEMOTRON_MODEL", "nvidia/nemotron-3-nano-30b-a3b")
NEMOTRON_ENABLED = bool(OPENROUTER_API_KEY or LOCAL_NEMOTRON_URL)

# Icarus markdown memory. "auto" means: use it if the icarus_memory package is
# importable, otherwise keep the business flow running and label it unavailable.
DAEDALUS_MEMORY_ENABLED = _env("DAEDALUS_MEMORY_ENABLED", "auto").lower()
DAEDALUS_MEMORY_ROOT = _env("DAEDALUS_MEMORY_ROOT", _env("ICARUS_FABRIC_ROOT", str(Path("~/fabric").expanduser())))


def status():
    """What is wired vs stubbed. Used by the CLI and tools to label honestly."""
    return {
        "project": PROJECT_NAME,
        "approval_mode": APPROVAL_MODE,
        "stripe": ("test" if STRIPE_TEST_MODE else "live-key!" if STRIPE_ENABLED
                   else "stub (pip install stripe)" if (STRIPE_SECRET_KEY and not STRIPE_LIB)
                   else "stub"),
        "nemotron": "openrouter" if OPENROUTER_API_KEY else ("local" if LOCAL_NEMOTRON_URL else "stub"),
        "memory": DAEDALUS_MEMORY_ENABLED,
    }

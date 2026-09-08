import os
from pathlib import Path

# Minimal .env loader so we don't need an extra dependency for this.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BOTS_DIR = DATA_DIR / "bots"
DB_PATH = DATA_DIR / "platform.db"

DATA_DIR.mkdir(exist_ok=True)
BOTS_DIR.mkdir(exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
JWT_SECRET = os.environ.get("JWT_SECRET")
FERNET_KEY = os.environ.get("FERNET_KEY")

if not ADMIN_PASSWORD or not JWT_SECRET or not FERNET_KEY:
    raise RuntimeError(
        "Missing ADMIN_PASSWORD, JWT_SECRET or FERNET_KEY. "
        "Copy server/.env.example to server/.env and fill in real values."
    )

SERVER_TOTAL_RAM_MB = int(os.environ.get("SERVER_TOTAL_RAM_MB", "3500"))
SERVER_TOTAL_CPU_CORES = float(os.environ.get("SERVER_TOTAL_CPU_CORES", "2"))
SERVER_TOTAL_STORAGE_MB = int(os.environ.get("SERVER_TOTAL_STORAGE_MB", "450000"))

JWT_ALGO = "HS256"
SESSION_HOURS = 12

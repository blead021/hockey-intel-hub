"""Settings read from environment variables, with the root .env file loaded for local runs."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Real environment variables (GitHub Actions secrets) win over the .env file.
load_dotenv(REPO_ROOT / ".env", override=False)


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


def database_url() -> str:
    """Direct (unpooled) connection, used by migrations and batch jobs."""
    name = "DATABASE_URL_UNPOOLED" if os.environ.get("DATABASE_URL_UNPOOLED") else "DATABASE_URL"
    url = require(name).strip()
    # Check the shape here, because the driver's own parse errors echo the password.
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError(
            f"{name} must start with postgresql://. Copy the whole value after the = sign in .env."
        )
    return url

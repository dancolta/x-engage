"""Config loader. Reads .env + YAML configs with sensible fallbacks to examples."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env()


def _bootstrap_ssl_certs() -> None:
    """Python 3.13 on macOS sometimes ships without a working cert bundle.
    Point urllib at certifi if SSL_CERT_FILE isn't already set.
    """
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass


_bootstrap_ssl_certs()


def _load_yaml(name: str) -> dict[str, Any]:
    """Load config/<name>.yml; fall back to config/<name>.example.yml if missing."""
    primary = ROOT / "config" / f"{name}.yml"
    fallback = ROOT / "config" / f"{name}.example.yml"
    path = primary if primary.exists() else fallback
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def settings() -> dict[str, Any]:
    return _load_yaml("settings")


def accounts() -> dict[str, Any]:
    return _load_yaml("accounts")


def topics() -> dict[str, Any]:
    return _load_yaml("topics")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def is_halted() -> bool:
    """Return True if any kill switch is engaged."""
    if env("X_ENGAGE_HALT", "0") == "1":
        return True
    paused_flag = Path.home() / ".x-engage" / "PAUSED"
    return paused_flag.exists()


# Panic ceilings — hardcoded, cannot be loosened by config
PANIC = {
    "daily_cap_max": 25,
    "min_gap_sec_floor": 30,
    "handle_cooldown_hours_floor": 12,
    "max_post_age_minutes": 90,
    "draft_min_chars_floor": 50,
    "draft_max_chars": 280,
}


def safe_int(value: Any, default: int, lower: int | None = None, upper: int | None = None) -> int:
    """Clamp a value between bounds; falls back to default on invalid input."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    if lower is not None and v < lower:
        return lower
    if upper is not None and v > upper:
        return upper
    return v

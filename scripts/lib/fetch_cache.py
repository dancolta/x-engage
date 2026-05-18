"""File-based fetch-pool cache + rate-limit cooldown marker.

Two purposes:
1. CACHE — back-to-back fetches within `fetch_cache_ttl_sec` reuse the bird
   response pool, eliminating repeat subqueries. The cache key combines the
   sorted subquery list with the from_date so different config states get
   different cache entries. Cached items pass through the normal age-window
   filter and seen-posts dedup downstream, so the queue still evolves.

2. COOLDOWN — when bird hits persistent rate-limit, we write a "cool until X"
   marker. The next fetch reads it and exits cleanly instead of burning more
   quota into an already-throttled window. Marker is auto-cleared once the
   cooldown timestamp passes.

Both files live under ~/.x-engage/ alongside the existing PAUSED flag.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import time
from pathlib import Path
from typing import Any

from . import log

CACHE_DIR = Path.home() / ".x-engage" / "cache"
COOLDOWN_FILE = Path.home() / ".x-engage" / "RATE_LIMIT_COOLDOWN"

# Default cooldown after a persistent rate-limit. 15 min matches X's rate-limit
# window for the search endpoint. Shorter = compounding 429s; longer = wasted
# idle time.
DEFAULT_COOLDOWN_SEC = 15 * 60


def _key(subqueries: list[tuple[str, str]], from_date: str) -> str:
    """Stable hash of (sorted subqueries, from_date). Different topic/accounts
    config or different day → different cache entry."""
    canonical = json.dumps(
        {"q": sorted([q for _, q in subqueries]), "d": from_date},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def load_pool(subqueries: list[tuple[str, str]], from_date: str,
              ttl_sec: int) -> list | None:
    """Return cached pool if fresh, else None.

    Pool is a list of SourceItem objects pickled to disk. Pickle is fine here
    — same-Python, never deserializes untrusted input.
    """
    if ttl_sec <= 0:
        return None
    path = CACHE_DIR / f"{_key(subqueries, from_date)}.pkl"
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl_sec:
        log.info("fetch_cache_expired", age_sec=int(age), ttl=ttl_sec)
        return None
    try:
        with path.open("rb") as f:
            pool = pickle.load(f)
        log.info("fetch_cache_hit", items=len(pool), age_sec=int(age))
        return pool
    except Exception as e:
        log.warn("fetch_cache_read_failed", err=str(e))
        return None


def save_pool(subqueries: list[tuple[str, str]], from_date: str,
              pool: list) -> None:
    if not pool:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = CACHE_DIR / f"{_key(subqueries, from_date)}.pkl"
        with path.open("wb") as f:
            pickle.dump(pool, f)
        log.info("fetch_cache_saved", items=len(pool))
    except Exception as e:
        log.warn("fetch_cache_save_failed", err=str(e))


def cooldown_seconds_remaining() -> int:
    """0 if no active cooldown, else seconds until it expires.

    Auto-removes a stale marker so the next call returns 0.
    """
    if not COOLDOWN_FILE.exists():
        return 0
    try:
        until = int(COOLDOWN_FILE.read_text().strip().splitlines()[0])
    except (ValueError, IndexError, OSError):
        try:
            COOLDOWN_FILE.unlink()
        except OSError:
            pass
        return 0
    remaining = until - int(time.time())
    if remaining <= 0:
        try:
            COOLDOWN_FILE.unlink()
        except OSError:
            pass
        return 0
    return remaining


def write_cooldown(seconds: int = DEFAULT_COOLDOWN_SEC, reason: str = "") -> None:
    """Mark rate-limit cooldown until now + seconds. Subsequent fetches exit
    cleanly until the timestamp passes.
    """
    try:
        COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        until = int(time.time()) + max(60, int(seconds))
        body = f"{until}\nReason: {reason}\nExpires: {time.ctime(until)}\n"
        COOLDOWN_FILE.write_text(body)
        log.warn("rate_limit_cooldown_set", seconds=seconds, until=until, reason=reason[:120])
    except Exception as e:
        log.warn("cooldown_write_failed", err=str(e))


def clear_cooldown() -> None:
    """Manual override — for the user to bust the cooldown if they know better."""
    try:
        if COOLDOWN_FILE.exists():
            COOLDOWN_FILE.unlink()
            log.info("rate_limit_cooldown_cleared")
    except OSError as e:
        log.warn("cooldown_clear_failed", err=str(e))

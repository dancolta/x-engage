"""Bird auth health check + cookie-expiry detection.

X session cookies (auth_token + ct0) expire periodically. When they do, bird
either fails the --check call or returns an `error` field with an auth-flavored
message on every subsequent search.

Helpers here let `fetch.py` and `cmd_setup` detect this cleanly:
  - `check_auth()` runs `bird --check` once → returns AuthStatus
  - `looks_like_auth_failure(response)` inspects a bird search response
  - `write_paused_for_cookies(reason)` writes the PAUSED flag with a clear message

PAUSED flag stops both `fetch` and `publish` runs until you fix it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import log

ROOT = Path(__file__).resolve().parents[2]
BIRD_MJS = ROOT / "scripts" / "lib" / "vendor" / "l30d" / "vendor" / "bird-search" / "bird-search.mjs"
PAUSED_FLAG = Path.home() / ".x-comment" / "PAUSED"

# Match common phrases X returns when the session is dead. Conservative — we
# only halt the run when we're confident, otherwise an unrelated 5xx would
# spuriously stop the tool.
_AUTH_FAIL_RE = re.compile(
    r"\b("
    r"401|403|"
    r"unauthorized|"
    r"not\s+authenticated|"
    r"authentication\s+(failed|required)|"
    r"auth_token|"
    r"ct0|"
    r"session\s+(expired|invalid)|"
    r"cookies?\s+(missing|expired|invalid)|"
    r"please\s+log\s+in|"
    r"login\s+required|"
    r"could\s+not\s+authenticate"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AuthStatus:
    authenticated: bool
    source: str = ""        # e.g. "env AUTH_TOKEN", "Safari"
    warnings: list[str] | None = None
    error: str | None = None


def check_auth(timeout: int = 18) -> AuthStatus:
    """Validate bird credentials.

    Two-stage check:
      1. `bird --check` → catches missing/empty cookies (presence test)
      2. A live search against the configured X session → catches expired-but-
         present cookies. The probe query is a single-letter generic term that
         X always returns results for when a session is valid; if it returns
         empty AND the env has cookies, we treat that as suspicious (likely
         expired) and surface AuthStatus(authenticated=False).

    Returns AuthStatus(authenticated=False, error=...) on any failure, never
    raises — callers can branch cleanly.
    """
    if not BIRD_MJS.exists():
        return AuthStatus(False, error=f"bird-search.mjs not found at {BIRD_MJS}")
    env = os.environ.copy()

    # Stage 1: presence check
    try:
        r = subprocess.run(
            ["node", str(BIRD_MJS), "--check"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return AuthStatus(False, error=f"bird --check timed out after {timeout}s")
    except FileNotFoundError:
        return AuthStatus(False, error="`node` not found on PATH (required for bird-search)")
    except Exception as e:
        return AuthStatus(False, error=f"bird --check failed: {e}")

    out = (r.stdout or "").strip()
    if not out:
        return AuthStatus(False, error=f"bird --check returned no JSON (stderr: {r.stderr[:200]})")
    try:
        presence = json.loads(out)
    except json.JSONDecodeError as e:
        return AuthStatus(False, error=f"bird --check non-JSON output: {e}")

    if not presence.get("authenticated"):
        return AuthStatus(
            authenticated=False,
            source=str(presence.get("source") or ""),
            warnings=presence.get("warnings") or None,
            error=presence.get("error") or "cookies not present",
        )

    # Stage 2: live probe — verify cookies actually work against X.
    # We search for "the" which always has fresh results when a valid session
    # is present. Empty result here = expired/invalid cookies.
    try:
        probe = subprocess.run(
            ["node", str(BIRD_MJS), "the", "--count", "3", "--json"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return AuthStatus(False, error="live probe timed out — likely expired session")
    except Exception as e:
        return AuthStatus(False, error=f"live probe failed: {e}")

    pout = (probe.stdout or "").strip()
    if not pout:
        return AuthStatus(False, error="live probe returned no output — likely expired session")
    try:
        pdata = json.loads(pout)
    except json.JSONDecodeError:
        return AuthStatus(False, error="live probe returned non-JSON — likely expired session")

    # Bird gracefully falls back to guest tokens if cookies are bad — search
    # still returns results, just with lower rate limits. So we only fail on
    # explicit error responses (X rejecting the session outright), not on
    # zero-result responses (which could be legit "no matches").
    if isinstance(pdata, dict) and pdata.get("error"):
        err = str(pdata["error"])
        if _AUTH_FAIL_RE.search(err):
            return AuthStatus(
                authenticated=False,
                source=str(presence.get("source") or ""),
                error=f"X rejected the session: {err}",
            )
        # Non-auth error (5xx, network) — surface but don't lock the user out
        return AuthStatus(
            authenticated=False,
            source=str(presence.get("source") or ""),
            error=f"live probe error: {err}",
        )

    # Cookies are present AND bird's pipeline works. Note: if X actually
    # silently downgraded to guest tokens we can't tell from here — the
    # fetch will still function with degraded rate limits.
    return AuthStatus(
        authenticated=True,
        source=str(presence.get("source") or ""),
    )


def looks_like_auth_failure(response: Any) -> bool:
    """Inspect a bird search response for auth-failure signals.

    Returns True only when the response contains an explicit auth-related
    error string (matched via _AUTH_FAIL_RE). Empty results = False (could be
    a legitimate "no recent posts" outcome we shouldn't pause on).
    """
    if not isinstance(response, dict):
        return False
    err = response.get("error")
    if not err:
        return False
    if isinstance(err, dict):
        err = err.get("message") or str(err)
    return bool(_AUTH_FAIL_RE.search(str(err)))


def write_paused_for_cookies(reason: str) -> Path:
    PAUSED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"{int(time.time())}: COOKIES_EXPIRED — {reason}\n\n"
        "How to fix:\n"
        "  1. Open x.com in Chrome, log out, log back in.\n"
        "  2. Open DevTools (Cmd+Opt+I) → Application → Cookies → https://x.com\n"
        "  3. Copy the Value of `auth_token` and `ct0` into .env as AUTH_TOKEN= and CT0=\n"
        "  4. Delete this file (~/.x-comment/PAUSED) to resume.\n"
    )
    PAUSED_FLAG.write_text(body)
    log.error("cookies_expired", reason=reason, paused_flag=str(PAUSED_FLAG))
    return PAUSED_FLAG

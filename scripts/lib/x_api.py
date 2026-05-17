"""Thin X (Twitter) API client via the open-source `xurl` CLI.

Inherits auth from existing xurl install (`xurl auth oauth2 login`).
Only two read operations are exposed: user timeline fetch + recent search.
Writes (replies) are NOT done via API — see scripts/publish.py for Playwright path.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

from . import log


@dataclass
class Tweet:
    id: str
    author_handle: str
    author_followers: int
    text: str
    created_at: int  # unix seconds
    url: str
    engagement: int  # likes + retweets + replies
    is_reply: bool
    is_retweet: bool
    is_quote: bool
    lang: str

    @property
    def age_minutes(self) -> float:
        return (time.time() - self.created_at) / 60.0


def is_available() -> bool:
    try:
        r = subprocess.run(["xurl", "whoami"], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and '"username"' in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def _xurl_get(path: str, timeout: int = 30) -> dict[str, Any]:
    """Run `xurl <path>` and return parsed JSON."""
    try:
        r = subprocess.run(["xurl", path], capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            log.warn("xurl_failed", path=path, stderr=r.stderr[:300])
            return {"error": r.stderr.strip() or "unknown xurl error"}
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        return {"error": f"xurl timeout: {path}"}
    except json.JSONDecodeError as e:
        return {"error": f"invalid JSON from xurl: {e}"}


def _parse_iso(s: str) -> int:
    """Parse X's RFC3339 timestamp to unix seconds. Best-effort, returns 0 on failure."""
    if not s:
        return 0
    try:
        from datetime import datetime, timezone
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).astimezone(timezone.utc).timestamp())
    except Exception:
        return 0


def _normalize_tweets(payload: dict[str, Any]) -> list[Tweet]:
    """Convert X API v2 response into Tweet objects.

    Expects payload with data[] + includes.users[]. Missing fields default to 0/"".
    """
    if "error" in payload:
        return []
    items = payload.get("data") or []
    users = {u["id"]: u for u in (payload.get("includes", {}).get("users") or [])}
    tweets: list[Tweet] = []
    for item in items:
        author_id = item.get("author_id", "")
        user = users.get(author_id, {})
        metrics = item.get("public_metrics", {})
        user_metrics = user.get("public_metrics", {})
        ref_types = {r.get("type") for r in (item.get("referenced_tweets") or [])}
        handle = user.get("username", "")
        tid = item.get("id", "")
        tweets.append(
            Tweet(
                id=tid,
                author_handle=handle,
                author_followers=int(user_metrics.get("followers_count", 0) or 0),
                text=item.get("text", ""),
                created_at=_parse_iso(item.get("created_at", "")),
                url=f"https://x.com/{handle}/status/{tid}" if handle and tid else "",
                engagement=sum(
                    int(metrics.get(k, 0) or 0)
                    for k in ("like_count", "retweet_count", "reply_count", "quote_count")
                ),
                is_reply="replied_to" in ref_types,
                is_retweet="retweeted" in ref_types,
                is_quote="quoted" in ref_types,
                lang=item.get("lang", ""),
            )
        )
    return tweets


def _common_fields() -> str:
    """Tweet + user fields we always want from the X API."""
    return (
        "tweet.fields=created_at,public_metrics,referenced_tweets,lang,author_id"
        "&user.fields=username,public_metrics"
        "&expansions=author_id"
    )


def user_timeline(handle: str, max_results: int = 10) -> list[Tweet]:
    """Fetch most recent original tweets from a user.

    Uses the X API v2 endpoint /2/users/by/username/<handle> → id, then
    /2/users/<id>/tweets. Excludes replies and retweets via the API itself
    so we get the smallest payload that still covers our needs.
    """
    lookup = _xurl_get(f"/2/users/by/username/{handle}")
    user = lookup.get("data") or {}
    user_id = user.get("id")
    if not user_id:
        log.warn("user_lookup_failed", handle=handle)
        return []
    path = (
        f"/2/users/{user_id}/tweets"
        f"?max_results={max(5, min(max_results, 100))}"
        f"&exclude=replies,retweets"
        f"&{_common_fields()}"
    )
    return _normalize_tweets(_xurl_get(path))


def search_recent(query: str, max_results: int = 20, lang: str = "en") -> list[Tweet]:
    """Search recent tweets via X API v2 /2/tweets/search/recent.

    Adds language filter and excludes retweets/replies at the query level.
    """
    full_query = f"{query} lang:{lang} -is:retweet -is:reply"
    path = (
        f"/2/tweets/search/recent"
        f"?query={_url_encode(full_query)}"
        f"&max_results={max(10, min(max_results, 100))}"
        f"&{_common_fields()}"
    )
    return _normalize_tweets(_xurl_get(path))


def _url_encode(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")

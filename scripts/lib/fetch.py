"""Candidate fetching pipeline — same architecture as /last30days for X search.

Provider: bird (vendored Node lib, reads X's GraphQL API using browser session cookies).
Bird returns minute-precision timestamps, which we preserve through the pipeline so the
"reply within 5–30 min" early-velocity window actually applies (vs. xAI's day-precision dates).

Pipeline (per fetch run):
  1. Build subqueries from accounts.yml (`from:@handle`) + topics.yml (raw queries).
  2. For each subquery: call bird → preserve full timestamp → normalize → signals.annotate_stream →
     prune_low_relevance → dedupe → snippet.extract_best_snippet.
  3. Cross-subquery dedup, sort by `local_rank_score` (composite from signals.py).
  4. Apply x-engage-specific filters: age window (5–60 min), per-handle cooldown,
     seen-posts, lifetime cap, follower bounds.

Modules in `vendor/l30d/` are vendored verbatim from /last30days so depth and output
quality match what /last30days returns for X via its bird backend.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import bird_health, claude_client, config, fetch_cache, log, state
from .vendor.l30d import (
    bird_x,
    dedupe as _dedupe,
    normalize as _normalize,
    planner as _planner,
    relevance as _relevance,
    schema as _schema,
    signals as _signals,
    snippet as _snippet,
)


SourceItem = _schema.SourceItem


def _build_subqueries() -> list[tuple[str, str]]:
    """Return [(label, search_query), ...].

    Subquery budget is tight by design to stay inside X's ~150 req/15min
    cookie limit:
      - Tracked accounts are OR-batched (`from:a OR from:b OR ...`) in
        groups of `account_or_batch_size` (default 9) instead of one
        subquery per handle. 18 handles → 2 subqueries.
      - Topics use ONLY the user's manual queries from topics.yml. Planner
        semantic expansion is OFF by default (`planner.enabled: false`) —
        the LLM produces worse paraphrases of what's already in topics.yml
        and burned 25+ extra bird calls per run. Set planner.enabled: true
        only if you observe missed candidates.
      - A global `max_subqueries_per_run` cap (default 35) truncates with
        a WARN if the total exceeds it, as a safety net against config
        drift (e.g. adding a 20th topic without thinking).
    """
    settings = config.settings()
    planner_cfg = settings.get("planner") or {}
    planner_enabled = bool(planner_cfg.get("enabled", False))
    planner_model = str(planner_cfg.get("model") or "claude-sonnet-4-6")
    planner_depth = str(planner_cfg.get("depth") or "default")
    or_batch_size = max(1, int(settings.get("account_or_batch_size", 9)))
    max_subs = max(1, int(settings.get("max_subqueries_per_run", 35)))

    subs: list[tuple[str, str]] = []
    seen_queries: set[str] = set()

    def _add(label: str, q: str) -> None:
        key = q.strip().lower()
        if key and key not in seen_queries:
            seen_queries.add(key)
            subs.append((label, q.strip()))

    # Tracked accounts — OR-batched
    acc_cfg = config.accounts()
    handles: list[str] = []
    for entry in (acc_cfg.get("accounts") or []):
        handle = entry.get("handle") if isinstance(entry, dict) else entry
        if handle:
            handles.append(str(handle).lstrip("@"))
    for i in range(0, len(handles), or_batch_size):
        chunk = handles[i:i + or_batch_size]
        if not chunk:
            continue
        q = " OR ".join(f"from:{h}" for h in chunk)
        label = f"accounts:batch{i // or_batch_size + 1}"
        _add(label, q)

    # Topics — manual queries only (planner OFF by default)
    provider = claude_client.build_provider() if planner_enabled else None
    topic_cfg = config.topics()
    for topic in (topic_cfg.get("topics") or []):
        name = str(topic.get("name") or "?")
        user_queries = [str(q) for q in (topic.get("queries") or []) if q]
        for q in user_queries:
            _add(name, q)
        # Optional planner expansion — disabled by default
        if provider:
            try:
                plan = _planner.plan_query(
                    topic=name + (" — " + ", ".join(user_queries) if user_queries else ""),
                    available_sources=["x"],
                    requested_sources=["x"],
                    depth=planner_depth,
                    provider=provider,
                    model=planner_model,
                    internal_subrun=True,
                )
                added = 0
                for sq in (plan.subqueries or []):
                    sq_text = (sq.search_query or "").strip()
                    if sq_text:
                        before = len(subs)
                        _add(name, sq_text)
                        if len(subs) > before:
                            added += 1
                log.info("planner_expansion", topic=name, added=added)
            except Exception as e:
                log.warn("planner_failed", topic=name, err=str(e))

    # Global cap — truncate with WARN if config drift pushed us past the budget
    if len(subs) > max_subs:
        log.warn("subquery_cap_truncated",
                 total=len(subs), cap=max_subs,
                 dropped=len(subs) - max_subs)
        subs = subs[:max_subs]
    return subs


def _topic_filters_for(label: str) -> dict[str, Any]:
    # Tracked-account subqueries (singular "account:" legacy + batched "accounts:")
    # skip the follower-band filter — those handles were pre-curated, so the
    # band rule doesn't apply.
    if label.startswith("account:") or label.startswith("accounts:"):
        return {"min_followers": 0, "max_followers": 10**9, "min_engagement_rate": 0.0}
    topic_cfg = config.topics()
    for topic in (topic_cfg.get("topics") or []):
        if str(topic.get("name") or "") == label:
            return {
                "min_followers": int(topic.get("min_followers", 0)),
                "max_followers": int(topic.get("max_followers", 10**9)),
                "min_engagement_rate": float(topic.get("min_engagement_rate", 0.0)),
            }
    return {"min_followers": 0, "max_followers": 10**9, "min_engagement_rate": 0.0}


def _engagement_followers(item: SourceItem) -> int:
    eng = item.engagement or {}
    for k in ("followers", "author_followers", "follower_count"):
        if k in eng:
            try:
                return int(eng[k] or 0)
            except (TypeError, ValueError):
                continue
    return 0


def _engagement_total(item: SourceItem) -> int:
    eng = item.engagement or {}
    total = 0
    for k in ("like_count", "likes", "retweet_count", "retweets", "reposts",
              "reply_count", "replies", "quote_count", "quotes"):
        try:
            total += int(eng.get(k) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _parse_bird_timestamp(created_at: str) -> str | None:
    """Convert bird's createdAt to an ISO timestamp string.

    Bird returns either:
      - "Sun May 17 18:26:58 +0000 2026"  (classic Twitter format)
      - "2026-05-17T18:26:58Z"            (occasional ISO)
    Both → "2026-05-17T18:26:58+00:00".
    """
    if not created_at:
        return None
    s = created_at.strip()
    try:
        if len(s) > 10 and s[10] == "T":
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%a %b %d %H:%M:%S %z %Y")
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


def _bird_search_with_precise_time(query: str, from_date: str, to_date: str,
                                   depth: str = "quick") -> list[dict[str, Any]]:
    """Wrapper around bird_x.search_x + parse_bird_response that preserves the
    full timestamp on each item (parse_bird_response normally strips it to YYYY-MM-DD).

    Returns list of item dicts in the same shape as bird_x.parse_bird_response,
    but with `date` set to a full ISO timestamp.

    Raises CookiesExpired if X rejects the session mid-fetch. Transient rate
    limits (HTTP 429) trigger a single back-off + retry; the second 429 returns
    an empty result list so the caller moves on to the next subquery rather
    than pausing the system.
    """
    import time as _time

    def _search_once() -> Any:
        return bird_x.search_x(query, from_date, to_date, depth=depth)

    response = _search_once()
    if bird_health.looks_like_rate_limit(response):
        log.warn("bird_rate_limited", query=query[:60], action="backoff 45s + retry once")
        _time.sleep(45)
        response = _search_once()
        if bird_health.looks_like_rate_limit(response):
            # Persistent rate-limit: write a cooldown marker so subsequent
            # fetch_candidates() calls exit cleanly until X's window clears,
            # instead of burning more quota into the same throttled state.
            fetch_cache.write_cooldown(reason=f"persistent 429 on subquery: {query[:60]}")
            log.warn("bird_rate_limited_persist", query=query[:60], action="skip + set cooldown")
            return []
    if bird_health.looks_like_auth_failure(response):
        err = str(response.get("error") if isinstance(response, dict) else response)
        bird_health.write_paused_for_cookies(f"bird search failed: {err}")
        raise CookiesExpired(err)
    parsed = bird_x.parse_bird_response(response, query=query)

    # parse_bird_response strips id (uses "X1", "X2", ...) and `date` to YYYY-MM-DD.
    # Map back to raw items by URL (parse_bird_response preserves it) so we can:
    # 1. Restore the real tweet id (needed for state.is_seen dedup)
    # 2. Replace `date` with full ISO timestamp from raw.createdAt
    raw_items = response if isinstance(response, list) else \
                response.get("items") or response.get("tweets") or []
    raw_by_url: dict[str, dict[str, Any]] = {}
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            rid = raw.get("id")
            author = (raw.get("author") or raw.get("user") or {})
            handle = author.get("username") or author.get("screen_name")
            if rid and handle:
                url = f"https://x.com/{handle}/status/{rid}"
                raw_by_url[url] = raw

    for item in parsed:
        raw = raw_by_url.get(item.get("url") or "")
        if not raw:
            continue
        precise = _parse_bird_timestamp(raw.get("createdAt") or raw.get("created_at") or "")
        if precise:
            item["date"] = precise  # full ISO; flows through normalize → SourceItem.published_at
        if raw.get("id"):
            item["id"] = str(raw["id"])  # real tweet id, replaces "X1"/"X2"/...
        # Inject author follower count into engagement dict so the follower-bounds
        # filter (and the SQLite source_followers column) actually have data to work
        # with. Bird's JS layer exposes it as author.followersCount; the vendored
        # parse_bird_response builds engagement but doesn't carry author metrics.
        author = (raw.get("author") or raw.get("user") or {})
        followers_raw = (author.get("followersCount")
                         if "followersCount" in author
                         else author.get("followers_count"))
        if followers_raw is not None:
            try:
                followers_int = int(followers_raw)
            except (TypeError, ValueError):
                followers_int = None
            if followers_int is not None:
                eng = item.get("engagement") or {}
                eng["followers"] = followers_int
                item["engagement"] = eng
    return parsed


def _age_minutes(published_at: str | None, now: datetime) -> float | None:
    if not published_at:
        return None
    s = published_at.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        pub = datetime.fromisoformat(s)
    except Exception:
        return None
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return (now - pub).total_seconds() / 60.0


class CookiesExpired(RuntimeError):
    """Raised by fetch_candidates when bird auth fails. Surfaces a
    machine-readable signal (`COOKIES_EXPIRED`) to the orchestrator so the
    skill wrapper can show the recovery instructions.
    """


def fetch_candidates() -> list[SourceItem]:
    """Return ranked, age-filtered X SourceItems ready for drafting.

    Raises CookiesExpired (subclass of RuntimeError) if bird auth fails. The
    PAUSED flag is also written so subsequent runs short-circuit.
    """
    if not (config.env("AUTH_TOKEN") and config.env("CT0")):
        log.error("missing_cookies",
                  hint="copy auth_token + ct0 from x.com DevTools cookies into .env")
        return []

    # Preflight: rate-limit cooldown from a previous run. Exit cleanly so we
    # don't burn quota into an already-throttled window. User can manually
    # bust it via `rm ~/.x-engage/RATE_LIMIT_COOLDOWN` if they know better.
    cooldown = fetch_cache.cooldown_seconds_remaining()
    if cooldown > 0:
        mins = (cooldown + 59) // 60
        log.warn("fetch_skipped_cooldown", seconds_remaining=cooldown)
        print(f"fetch: rate-limit cooldown active ({mins} min remaining). "
              f"X is throttling; bird calls would just hit 429. "
              f"To override: rm ~/.x-engage/RATE_LIMIT_COOLDOWN")
        return []

    # Preflight: validate cookies before spending time / API calls
    health = bird_health.check_auth()
    if not health.authenticated:
        reason = health.error or "; ".join(health.warnings or []) or "unknown auth failure"
        bird_health.write_paused_for_cookies(reason)
        raise CookiesExpired(reason)

    settings = config.settings()
    cooldown_hours = config.safe_int(
        settings.get("handle_cooldown_hours", 24), 24,
        lower=config.PANIC["handle_cooldown_hours_floor"], upper=168,
    )
    overlay_min = config.safe_int(settings.get("min_age_minutes", 5), 5, 0, 60)
    overlay_max = config.safe_int(
        settings.get("max_age_minutes", 60), 60, 5,
        config.PANIC["max_post_age_minutes"],
    )

    now = datetime.now(timezone.utc)
    # Bird's `since:YYYY-MM-DD` operator. Today only is enough since we age-filter <60 min.
    from_date = now.strftime("%Y-%m-%d")
    # filter_by_date_range does lexicographic compare; pad to_date to tomorrow so
    # full-ISO timestamps (which sort > "YYYY-MM-DD") aren't dropped.
    to_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    subqueries = _build_subqueries()
    if not subqueries:
        log.warn("no_subqueries",
                 hint="add accounts to config/accounts.yml or topics to config/topics.yml")
        return []
    log.info("subqueries_built", count=len(subqueries))

    # Cache hit short-circuits the whole bird/normalize/signals stack.
    # Downstream filters (age window, seen-posts, cooldown, follower band)
    # still run against the cached pool so the queue still evolves between
    # calls — we just don't re-hit X.
    cache_ttl = int(settings.get("fetch_cache_ttl_sec", 300))
    cached_pool = fetch_cache.load_pool(subqueries, from_date, cache_ttl)
    if cached_pool is not None:
        all_items = cached_pool
    else:
        all_items = []

    for label, q in subqueries if cached_pool is None else []:
        log.info("bird_search", label=label, query=q[:80])
        try:
            parsed = _bird_search_with_precise_time(q, from_date, to_date, depth="quick")
        except Exception as e:
            log.warn("bird_search_failed", label=label, err=str(e))
            continue
        if not parsed:
            log.info("bird_search_empty", label=label)
            continue

        normalized = _normalize.normalize_source_items(
            "x", parsed, from_date, to_date, freshness_mode="recent_only",
        )
        prepared_query = _relevance.PreparedQuery(q)
        normalized = _signals.annotate_stream(normalized, prepared_query, "recent_only")
        normalized = _signals.prune_low_relevance(normalized)
        normalized = _dedupe.dedupe_items(normalized)
        for item in normalized:
            item.snippet = _snippet.extract_best_snippet(item, prepared_query)
            item.metadata["subquery_label"] = label
            item.metadata["subquery"] = q

        all_items.extend(normalized)
        log.info("bird_search_done", label=label, returned=len(normalized))

    if not all_items:
        return []

    # Cache the cold-fetched pool so the next call within fetch_cache_ttl_sec
    # reuses it. Only cache fresh fetches, not pools we just loaded from cache.
    if cached_pool is None:
        fetch_cache.save_pool(subqueries, from_date, all_items)

    all_items = _dedupe.dedupe_items(all_items)
    all_items.sort(key=lambda i: i.local_rank_score or 0.0, reverse=True)

    # x-engage-specific filters
    filtered: list[SourceItem] = []
    for item in all_items:
        author = (item.author or "").lstrip("@").strip()
        if not author:
            continue
        age_min = _age_minutes(item.published_at, now)
        if age_min is None:
            continue
        if not (overlay_min <= age_min <= overlay_max):
            continue
        if state.is_seen(item.item_id):
            continue
        if state.is_on_cooldown(author.lower(), cooldown_hours):
            continue
        if state.lifetime_replies_to(author.lower(), within_days=30) >= 4:
            continue

        bounds = _topic_filters_for(str(item.metadata.get("subquery_label") or ""))
        followers = _engagement_followers(item)
        # Fail-closed: if min_followers > 0 and we don't have a count, skip the
        # post rather than letting it through. Prevents the previous bug where
        # unparseable follower data silently bypassed the filter and let
        # small accounts through under topic-search queries.
        if bounds["min_followers"] > 0 and followers <= 0:
            log.info("filter_skip_no_followers", author=author, label=item.metadata.get("subquery_label"))
            continue
        if followers and not (bounds["min_followers"] <= followers <= bounds["max_followers"]):
            continue
        if followers and bounds["min_engagement_rate"] > 0:
            er = _engagement_total(item) / max(followers, 1)
            if er < bounds["min_engagement_rate"]:
                continue

        item.metadata["age_min"] = int(age_min)
        filtered.append(item)

    log.info("candidates_ready", pool=len(all_items), kept=len(filtered))
    return filtered

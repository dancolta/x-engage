"""Candidate fetching: Filter 1 (tracked accounts) then Filter 2 (topic search).

Newest-first, hard age cap, dedup against seen_posts + handles_cooldown.
"""

from __future__ import annotations

from . import config, log, state, x_api
from .x_api import Tweet


def _apply_age_filter(tweets: list[Tweet], min_min: int, max_min: int) -> list[Tweet]:
    return [t for t in tweets if min_min <= t.age_minutes <= max_min]


def _apply_type_filter(tweets: list[Tweet], skip_replies: bool, skip_retweets: bool,
                       skip_quotes: bool) -> list[Tweet]:
    out = []
    for t in tweets:
        if skip_replies and t.is_reply:
            continue
        if skip_retweets and t.is_retweet:
            continue
        if skip_quotes and t.is_quote:
            continue
        out.append(t)
    return out


def _apply_cooldown_filter(tweets: list[Tweet], cooldown_hours: int) -> list[Tweet]:
    return [t for t in tweets if not state.is_on_cooldown(t.author_handle, cooldown_hours)]


def _apply_seen_filter(tweets: list[Tweet]) -> list[Tweet]:
    return [t for t in tweets if not state.is_seen(t.id)]


def fetch_candidates() -> list[Tweet]:
    """Return ordered candidate Tweets (newest first), deduped + filtered."""
    settings = config.settings()
    cooldown_hours = config.safe_int(
        settings.get("handle_cooldown_hours", 24), 24,
        lower=config.PANIC["handle_cooldown_hours_floor"], upper=168,
    )

    candidates: list[Tweet] = []

    # --- Filter 1: tracked accounts ---
    acc_cfg = config.accounts()
    acc_rules = acc_cfg.get("rules") or {}
    acc_min = config.safe_int(acc_rules.get("min_age_minutes", 5), 5, 0, 60)
    acc_max = config.safe_int(acc_rules.get("max_age_minutes", 60), 60, 5,
                              config.PANIC["max_post_age_minutes"])
    for entry in (acc_cfg.get("accounts") or []):
        handle = entry.get("handle") if isinstance(entry, dict) else entry
        if not handle:
            continue
        tweets = x_api.user_timeline(handle, max_results=10)
        tweets = _apply_age_filter(tweets, acc_min, acc_max)
        tweets = _apply_type_filter(
            tweets,
            skip_replies=acc_rules.get("skip_replies", True),
            skip_retweets=acc_rules.get("skip_retweets", True),
            skip_quotes=acc_rules.get("skip_quote_tweets", False),
        )
        candidates.extend(tweets)
        log.info("tracked_account_fetched", handle=handle, count=len(tweets))

    # --- Filter 2: topic / keyword search ---
    topic_cfg = config.topics()
    topic_rules = topic_cfg.get("rules") or {}
    t_min = config.safe_int(topic_rules.get("min_age_minutes", 5), 5, 0, 60)
    t_max = config.safe_int(topic_rules.get("max_age_minutes", 60), 60, 5,
                            config.PANIC["max_post_age_minutes"])
    lang = topic_rules.get("language", "en")
    excluded = {h.lower() for h in (topic_rules.get("exclude_handles") or [])}
    for topic in (topic_cfg.get("topics") or []):
        name = topic.get("name", "?")
        min_followers = int(topic.get("min_followers", 5000))
        max_followers = int(topic.get("max_followers", 250000))
        min_er = float(topic.get("min_engagement_rate", 0.01))
        n_per_q = config.safe_int(topic.get("max_results_per_query", 20), 20, 10, 100)
        for query in (topic.get("queries") or []):
            tweets = x_api.search_recent(query, max_results=n_per_q, lang=lang)
            tweets = _apply_age_filter(tweets, t_min, t_max)
            tweets = _apply_type_filter(
                tweets,
                skip_replies=topic_rules.get("skip_replies", True),
                skip_retweets=topic_rules.get("skip_retweets", True),
                skip_quotes=topic_rules.get("skip_quote_tweets", False),
            )
            tweets = [t for t in tweets if t.author_handle.lower() not in excluded]
            tweets = [t for t in tweets if min_followers <= t.author_followers <= max_followers]
            tweets = [t for t in tweets if _engagement_rate(t) >= min_er]
            candidates.extend(tweets)
            log.info("topic_query_fetched", topic=name, query=query, count=len(tweets))

    # --- Dedup + cooldown + seen ---
    by_id: dict[str, Tweet] = {}
    for t in candidates:
        by_id[t.id] = t  # last-write-wins, but identical tweets are identical
    deduped = list(by_id.values())
    deduped = _apply_cooldown_filter(deduped, cooldown_hours)
    deduped = _apply_seen_filter(deduped)

    # --- Sort newest-first ---
    deduped.sort(key=lambda t: t.age_minutes)
    log.info("candidates_ready", total=len(deduped))
    return deduped


def _engagement_rate(t: Tweet) -> float:
    if t.author_followers <= 0:
        return 0.0
    return t.engagement / t.author_followers

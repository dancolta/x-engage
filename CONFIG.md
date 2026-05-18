# Full configuration reference

Every config key x-engage reads, grouped by file. Most users only need to touch the **Quick-edit** keys called out in the main [README](README.md#configuration).

---

## `.env` (gitignored — never commit)

| Variable | Required | Notes |
|---|---|---|
| `AUTH_TOKEN` | Yes | X session cookie. ~40 chars. Setup wizard helps you grab it. |
| `CT0` | Yes | X session cookie. ~160 chars. Setup wizard helps you grab it. |
| `NOTION_TOKEN` | No | Notion integration token. Skip to disable the Notion mirror entirely. |
| `NOTION_DB_ID` | No | 32-char hex from your Notion DB URL. |
| `CLAUDE_CLI` | No | Defaults to `claude`. Override if your binary is elsewhere. |
| `X_ENGAGE_HALT` | No | Set to `1` to halt all pipeline stages. Kill switch. |
| `X_PROFILE_DIR` | No | Playwright Chrome profile dir. Defaults to `~/.x-engage/chrome-profile`. |

---

## `config/settings.yml`

### Volume & cadence

| Key | Default | Notes |
|---|---|---|
| `daily_cap` | — | **Deprecated.** No longer enforced. Use the count arg on fetch: `/x-engage fetch 30`. |
| `min_gap_between_publishes_sec` | 90 | Floor between publishes. Code refuses values < 30. |
| `voice_match_threshold` | 0.45 | Drafts below this score are auto-rejected. |

### Reply window

| Key | Default | Notes |
|---|---|---|
| `min_age_minutes` | 5 | Posts younger than this are skipped (OP might still be editing). |
| `max_age_minutes` | 90 | Posts older than this are skipped (reply slot is gone). |

### Discovery budget

| Key | Default | Notes |
|---|---|---|
| `max_subqueries_per_run` | 35 | Hard ceiling on bird subqueries per fetch run. |
| `account_or_batch_size` | 9 | OR-batch tracked-account queries in groups of this size. X allows ~10 per query. |
| `fetch_cache_ttl_sec` | 300 | Cache TTL for the discovery pool between back-to-back fetches. |

### Posting windows

| Key | Default | Notes |
|---|---|---|
| `tz` | `UTC` | Target audience timezone, for daily-cap reset boundary. |
| `posting_windows` | Tue–Thu 8–11am + 3pm | Research-backed peaks. Used by optional launchd schedule. |
| `jitter_window_minutes` | `[20, 80]` | Random delay between posting windows. |

### Safety

| Key | Default | Notes |
|---|---|---|
| `require_explicit_approval` | `true` | Code refuses to flip this to false. Defense-in-depth. |
| `handle_cooldown_hours` | 24 | Min hours between any two replies to the same author. |
| `banned_terms` | `[]` | Custom blocklist — terms that auto-reject any draft containing them. |

### Planner (optional)

| Key | Default | Notes |
|---|---|---|
| `planner.enabled` | `false` | LLM-driven semantic expansion of topic queries. Off by default — your manual queries are usually tighter. |
| `planner.model` | `claude-sonnet-4-6` | Model used by planner when enabled. |
| `planner.depth` | `default` | `quick` / `default` / `deep`. More = more subqueries. |

### Notion

| Key | Default | Notes |
|---|---|---|
| `notion.mirror_enabled` | `true` | Set false to skip Notion writes (SQLite still works). |
| `notion.status_field` | `Status` | Column name in your Notion DB. |

### Logging

| Key | Default | Notes |
|---|---|---|
| `log_level` | `INFO` | `DEBUG` / `INFO` / `WARN` / `ERROR`. |

---

## `config/topics.yml`

Each `topics:` entry is a search-query batch with per-topic filter overrides.

```yaml
topics:
  - name: my_topic
    queries:
      - 'search query string'
      - 'another query'
    min_followers: 2000          # author follower band lower bound
    max_followers: 25000         # upper bound (Goldilocks ceiling)
    min_engagement_rate: 0       # 0 = off. The early-reply slot doesn't have engagement yet.
    max_results_per_query: 15    # cap per individual query
```

### Recommended values (per current research)

| Filter | Value | Reasoning |
|---|---|---|
| `min_followers` | 2000 | Excludes the smallest accounts that have no algorithmic distribution. |
| `max_followers` | 25000 | Mega-account threads bury your reply. 25K is the Goldilocks ceiling. |
| `min_engagement_rate` | 0 | The 5-90 min reply window doesn't have engagement yet. Use X search operators like `min_replies:N` in the query string instead for query-time filtering. |

### Global rules

```yaml
rules:
  language: en
  max_age_minutes: 90
  min_age_minutes: 5
  skip_replies: true
  skip_retweets: true
  skip_quote_tweets: false
  exclude_handles:
    - some_handle_to_block
```

### Query patterns that work

Use **co-occurrence anchoring** (multiple specific words in same post):

```yaml
- '"replaced" "Claude Code" -is:retweet'
- '"killed our" "subscription" -is:retweet'
- '"vibe coded" "weekend" -is:retweet'
- '"shipped" "Claude Code" -is:retweet min_replies:1'
```

X search operators that work in queries:

| Operator | Effect |
|---|---|
| `"phrase"` | Exact-match phrase |
| `WORD OR WORD` | Match either |
| `"a" "b"` | AND (both phrases must appear) |
| `-is:retweet` | Exclude retweets |
| `-filter:replies` | Exclude reply posts |
| `min_replies:N` | Parent must have ≥N replies |
| `min_faves:N` | Parent must have ≥N likes |
| `lang:en` | English only |

Avoid single ambiguous terms (`"renting"`, `"per seat"`, `"won't fix"`) — they match noise like rent commentary, sports stadiums, legal news.

---

## `config/accounts.yml`

```yaml
accounts:
  - handle: example_handle_1
  - handle: example_handle_2
  # ... up to ~20-30 handles. OR-batched in groups of 9 per query.
```

Tracked accounts skip the follower-band check (you pre-curated them). Per-handle cooldown + lifetime cap still apply.

---

## `voice-profile.personal.md`

Your underlying voice DNA. Required, gitignored. Copy from `voice-profile.example.md` and edit.

The skill reads only `voice-profile.personal.md` — the example file is a starter template that never loads into the drafter.

Key sections to customize:
- **Positioning** — what you do, what you don't do
- **Voice in one line** — the elevator pitch for your register
- **Tone patterns** — your tics, fillers, sentence shapes
- **Banned credential moves** — what NOT to imply
- **Good reply examples** — 5-10 examples in your actual voice

---

## `references/x-overlay.md`

X-platform constraints layered on top of your voice profile. Edit when X behavior changes; don't touch your voice file.

Contains:
- Length bands (60–110 punch / 190–240 earned-long)
- T1–T7 reply structure templates
- Banned openers (per Phoenix-ranker spam detection)
- Profile-click framing levers
- Quote / em-dash / hashtag bans

---

## `good-drafts.md` (optional but recommended)

Vibe-reference learning loop. Copy `good-drafts.example.md` → `good-drafts.md` (gitignored). When you mark a draft `good` via `/x-engage good <id>`, it appends to this file.

On next fetch, the drafter samples 3 random examples as mood references (NOT templates — a 4-gram overlap lint prevents copy-paste).

Auto-trims to most recent 25 entries.

---

## Hardcoded ceilings (cannot be loosened via config)

These live in `scripts/lib/config.py` as the `PANIC` dict:

| Ceiling | Value | What it caps |
|---|---|---|
| `daily_cap_max` | 25 | Hard upper bound if `daily_cap` were re-enabled |
| `min_gap_sec_floor` | 30 | Cannot publish faster than 30s gap |
| `handle_cooldown_hours_floor` | 12 | Cannot reply twice to same handle in < 12h |
| `max_post_age_minutes` | 1440 | Cannot extend reply window past 24h |
| `safety_length_floor` | 60 | Cannot draft replies shorter than 60 chars |
| `safety_length_ceiling` | 280 | X's hard limit |

---

## Where files live

| Path | Tracked in git | Purpose |
|---|---|---|
| `.env` | No | Secrets (cookies, Notion token) |
| `.env.example` | Yes | Template |
| `config/*.yml` | No | Your live config |
| `config/*.example.yml` | Yes | Starter templates |
| `voice-profile.personal.md` | No | Your voice (gitignored) |
| `voice-profile.example.md` | Yes | Starter template |
| `good-drafts.md` | No | Your vibe references |
| `good-drafts.example.md` | Yes | Starter template |
| `references/x-overlay.md` | Yes | Platform constraints |
| `references/guardrails.md` | Yes | Safety reasoning doc |
| `state/x-engage.sqlite` | No | Draft queue, candidate pool, cooldowns |
| `~/.x-engage/PAUSED` | No | Kill-switch flag file |
| `~/.x-engage/RATE_LIMIT_COOLDOWN` | No | Bird cooldown marker |
| `~/.x-engage/chrome-profile/` | No | Playwright persistent X session |
| `~/Library/LaunchAgents/com.x-engage.scan-bg.plist` | No | Daemon launchd config (when running) |

# x-engage

x-engage cuts out the 30–60 minutes you'd otherwise spend scrolling X to find a post worth replying to. It watches a list of accounts and keywords you define, scores each post against simple criteria (recency, follower band, engagement velocity), drafts a reply in your voice, and stops. You read it, edit it or kill it, then hit publish. That's the whole loop.

The philosophy: replies are only worth sending if you actually mean them. This tool is a curation layer, not an output multiplier. It doesn't help you reply more — it helps you spend less time deciding where to reply at all.

It's not in the same category as ReplyGuyApp, Replier, or any other tool that fires replies at scale on your behalf. Those tools treat your account as a broadcast channel. This one treats your account as yours. Every reply is read and approved by you before it leaves your machine.

The background daemon (opt-in, runs every 10 minutes) only builds the candidate queue. Drafting and publishing are both explicit actions you take in chat. There is no mode where the tool acts without you.

![demo](assets/demo.gif)

---

## ⚠️ Before you install — read this

This tool drives a **logged-in browser session** on a real X account via Playwright. X's [automation rules](https://help.x.com/en/rules-and-policies/twitter-automation) prohibit certain automated activity. You are responsible for staying inside them.

- The defaults (15 replies/day, 24h per-handle cooldown, 90-120s jittered gap between publishes, human-typed input, single device fingerprint) are research-tuned to look like a person who reads X actively for ~25 minutes and replies as they go. They are **not a guarantee** that an account won't be limited.
- Hard caps are enforced in code (`references/guardrails.md`) and **cannot be loosened via config**. Even if `config/settings.yml` says 50/day, the code uses 25.
- If you crank volume or run multiple accounts, you will get flagged. Don't.
- Every reply goes through chat approval. There is **no fully autonomous mode**. This is by design.

If your account is a critical business asset and you're not okay with any incremental risk, use the [official X API](https://docs.x.com/x-api/getting-started/about-x-api) paid tier with write scope instead of Playwright.

---

## What this is (and isn't)

**Is:**
- A signal filter. Pulls only from `accounts.yml` (handles you curated) + `topics.yml` (keywords you defined) — not a firehose
- A follower-band filter. Default 2K–25K (sweet spot 6K–15K, per 3-agent algo + competitive + framing research): skips mega accounts where your reply is buried in a thousand-comment thread, and skips micro accounts where the thread has no audience
- A post-age filter. Default 5–35 min reply window: catches the early-velocity slot where replies get 3–5x more visibility than late slots, before the Phoenix ranker stops feeding the parent post
- A drafting assistant. Generates a reply you can approve, redraft with one line of feedback, or kill
- Fully human-gated. Every reply requires your explicit `approve` then `publish`. No autonomous mode exists and the code won't let you enable one
- Volume self-policed. No daily cap on drafts or publishes — you decide via the optional count arg (`/x-engage fetch 30`) and explicit approval. Per-handle 24h cooldown + 4/30d lifetime cap + 90-120s publish gap stay as the safety belt

**Isn't:**
- A mass-reply bot or follower-growth hack
- A DM tool (doesn't touch DMs)
- A scheduler that publishes on your behalf while you sleep
- A scraper of strangers' content — only fetches posts from accounts and topics you explicitly defined
- A guarantee against X flagging your account (see the warning section above)

---

## How it works

```
Build subqueries from accounts.yml (from:@handle) + topics.yml (keywords)
                       │
                       ▼
       For each subquery:
         bird_x.search_x()       ← X GraphQL via your session cookies, free, minute-precision timestamps
       → parse_bird_response() (+ timestamp preservation shim)
       → normalize_source_items()
       → signals.annotate_stream()    (relevance + freshness + engagement)
       → signals.prune_low_relevance()
       → dedupe.dedupe_items()
       → snippet.extract_best_snippet()
                       │
                       ▼
       Cross-subquery dedup + sort by local_rank_score
                       │
                       ▼
       Age window (5–35 min) + cooldown + seen-posts + follower bounds (2K–25K)
                       │
                       ▼
       voice-profile.personal.md + x-overlay.md + Claude CLI → draft reply
                       │
                       ▼
       safety lint + voice score
                       │
                       ▼
       SQLite queue ◄──┼──► Notion mirror (log only, optional)
                       │
                       ▼
       you, in chat: review · approve · redraft · kill
                       │
                       ▼
       Playwright posts to X (headed, humanized)
```

Your `accounts.yml` and `topics.yml` define the input universe. The pipeline queries those handles and keywords, scores each post on relevance + freshness + engagement, enforces the follower-band filter, deduplicates across queries, and drops everything that doesn't clear the threshold. What survives gets a draft reply generated against your `voice-profile.personal.md`. Safety lint runs, voice score gates, and the remainder lands in a SQLite queue.

From there it's entirely yours: `fetch` builds the queue, `review` surfaces it in chat, `approve` or `kill` each draft, `redraft <id> "<feedback>"` if the draft is close but not right, `good <id>` to save a draft as a vibe reference for future runs, `publish` to ship what you approved. That's the whole loop.

The discovery pipeline (`bird_x → normalize → signals → dedupe → snippet`) is vendored verbatim from the [`last30days`](https://github.com/dancolta/last30days) skill into `scripts/lib/vendor/l30d/`, so candidate quality and ranking match what `/last30days` produces for X. Bird uses your browser session cookies (`AUTH_TOKEN` + `CT0` from `.env`) and runs as a Node subprocess — same auth model as your Playwright posting setup, zero API cost.

The reply-drafting voice is defined in `voice-profile.personal.md` (gitignored — copy `voice-profile.example.md` to it and edit). `references/x-overlay.md` layers X-specific constraints on top — character minimums, opener rotation, banned spam triggers, constructive-tone requirement (the Jan 2026 Grok ranker actively suppresses combative replies regardless of engagement).

## Quick start

### 1. Prerequisites

- macOS (the launchd plist is mac-flavored; on Linux swap for cron / systemd)
- Python 3.10+
- Node.js 22+ (the vendored `bird-search` reader runs on Node)
- [Claude Code](https://claude.ai/code) CLI on PATH
- A logged-in X account — you'll copy two session cookies (`auth_token` and `ct0`) into `.env`. **No paid API needed.**
- A Notion integration token + a database (optional — set `mirror_enabled: false` to skip)

### 2. Install

```bash
git clone https://github.com/dancolta/x-engage.git
cd x-engage
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure

```bash
cp .env.example .env                              # add AUTH_TOKEN + CT0 (required) + NOTION_TOKEN/NOTION_DB_ID (optional)
cp config/accounts.example.yml config/accounts.yml
cp config/topics.example.yml   config/topics.yml
cp config/settings.example.yml config/settings.yml
```

To grab `AUTH_TOKEN` and `CT0`:
1. Open **x.com** in Chrome, logged in
2. DevTools (Cmd+Opt+I) → **Application** tab → **Cookies → https://x.com**
3. Copy the **Value** column for `auth_token` (~40 chars) and `ct0` (~160 chars)
4. Paste into `.env` as `AUTH_TOKEN=...` and `CT0=...`

Cookies expire when you log out of x.com. Re-grab if `bird-search` starts returning empty results.

Edit each file:

- **`config/accounts.yml`** — handles you reply to often (5k–250k followers convert best per research)
- **`config/topics.yml`** — keyword searches mapped to topic buckets
- **`config/settings.yml`** — daily cap, timezone, posting windows, voice-match threshold
- **`voice-profile.personal.md`** — your underlying voice. **Required, gitignored.** Copy `voice-profile.example.md` to `voice-profile.personal.md` and edit. The skill only ever reads `voice-profile.personal.md` — the example file is a starter template, never loaded (no token waste, no leaked voice signals to/from the public repo).
- **`references/x-overlay.md`** — X-specific constraints (length floor, opener rotation, banned patterns)

### 4. Notion database (optional)

If you want a searchable log of drafts (Notion is **not** the approval surface — chat is), create a Notion DB with these properties (names are **case-sensitive, lowercase**):

| Property | Type | Notes |
|---|---|---|
| Name | Title | Auto-filled with `@author: source preview` |
| status | Select | Options: `pending`, `approved`, `publishing`, `published`, `failed`, `skipped`, `deferred` |
| author | Text | Source post author handle |
| draft | Text | Generated reply |
| final_text | Text | Optional — your edits land here, used instead of `draft` if set |
| post_text | Text | Source post text |
| post_url | URL | Source tweet URL |
| scanned_at | Date | When the draft was created |
| published_at | Date | When the reply was published |
| reason | Text | Filled on skip/fail/defer |

Share the DB with your Notion integration. Copy the DB ID from the URL into `.env` as `NOTION_DB_ID`. To skip Notion entirely, set `notion.mirror_enabled: false` in `config/settings.yml`.

### 5. Log in to X once (in the persistent profile Playwright will reuse)

This is the only time the browser opens visibly — after login, all subsequent publish runs are headless.

```bash
python3 -c "
from playwright.sync_api import sync_playwright
from pathlib import Path
import os
profile = os.path.expanduser('~/.x-engage/chrome-profile')
Path(profile).mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(profile, headless=False, viewport={'width':1280,'height':800})
    page = ctx.new_page()
    page.goto('https://x.com/login')
    input('Log in to X manually, then press Enter to close...')
    ctx.close()
"
```

### 6. Verify setup

```bash
python3 -m scripts.x_engage setup
```

Expected output:
```
[ok] X session cookies (AUTH_TOKEN + CT0) present
[ok] node on PATH (required for bird-search)
[ok] Notion env vars present
[ok] claude CLI on PATH
[info] Playwright profile dir: ~/.x-engage/chrome-profile
```

## Usage

The skill installs as `/x-engage` in Claude Code. From the CLI directly:

| Command | What it does |
|---|---|
| `python3 -m scripts.x_engage fetch` | Pull candidates, draft, queue (also mirrors to Notion if enabled) |
| `python3 -m scripts.x_engage review` | Show all pending drafts in chat-ready format |
| `python3 -m scripts.x_engage approve <ids\|all>` | Mark drafts approved |
| `python3 -m scripts.x_engage redraft <id> "<feedback>"` | Re-draft one row with your steer |
| `python3 -m scripts.x_engage kill <id>` | Reject a draft |
| `python3 -m scripts.x_engage good <id>` | Save a draft as a vibe reference for future drafting |
| `python3 -m scripts.x_engage publish` | Ship approved drafts via Playwright |
| `python3 -m scripts.x_engage status` | Counts, daily cap, paused state |
| `python3 -m scripts.x_engage run-bg` | Install + start the background daemon (10-min scan interval, opt-in) |
| `python3 -m scripts.x_engage stop-bg` | Stop the daemon (pool stays usable) |
| `python3 -m scripts.x_engage bg-status` | Daemon state + candidate pool size + last fetch age |

Typical day:

```
$ /x-engage fetch
fetch: drafted=4, skipped=11, rejected=2, candidates=17

$ /x-engage review
#a1b2c3d4  @builder_42 (12,400 followers) · 8min ago · score 0.91
  Source: "We doubled our revenue in 30 days using only AI."
  Draft:  "What was the baseline though. Doubling from 2k to 4k and from 200k to 400k are different conversations entirely."

#e5f6g7h8  @founder_99 (45,200 followers) · 22min ago · score 0.78
  Source: "Custom dev is dead, no-code wins."
  Draft:  "Depends on what you're building. The recurring SaaS items piling up in most teams are weekend-overnight territory now, anything load-bearing is still custom."

Reply with: approve <ids|all>, redraft <id>: <feedback>, kill <id>, or publish

$ /x-engage approve a1b2c3d4
approve: marked 1 draft(s) approved. Run `/x-engage publish` to ship.

$ /x-engage redraft e5f6g7h8: more direct, drop the comma splice
redraft #e5f6g7h8: score 0.84
  Draft: "Depends on what you're building. The SaaS subscriptions stacking up in most teams are weekend-overnight territory now. Anything load-bearing for the business is still custom."

$ /x-engage approve all
approve: marked 1 draft(s) approved. Run `/x-engage publish` to ship.

$ /x-engage publish
publish: published=2, failed=0, deferred=0
```

## Background daemon (recommended)

Without the daemon, every `/x-engage fetch` fires 33 bird subqueries live — easy to hit X's 150 req/15 min cookie rate limit. With the daemon, those subqueries run **in the background every 10 min** via macOS launchd, surface candidates into a SQLite pool, and your interactive `/x-engage fetch` just reads from the pool and drafts. 15 drafts in ~3 min instead of 1-2 hours.

```bash
/x-engage run-bg      # install + load launchd plist, daemon starts firing every 10 min
/x-engage bg-status   # check it's running, see pool size + last-fetch age
/x-engage fetch       # reads from pool when warm; falls back to live fetch when empty
/x-engage stop-bg     # unload the daemon (existing pool stays usable)
```

How the split works:
- **Daemon (`scan-bg` subcommand)** — Discovery only. Hits bird/Lists, runs filter chain, writes survivors to `candidate_pool` SQLite table. Auto-evicts rows older than 1 hour. Never touches Notion. Never drafts.
- **Interactive `/x-engage fetch`** — Drafting only when pool is warm. Reads top-scored candidates from the pool, calls Claude CLI drafter, applies safety lint + voice score, inserts passing drafts into the `drafts` queue, mirrors to Notion. Falls back to live discovery when pool is empty (zero behavior change vs. without the daemon).

Daemon is **opt-in**. Default = off. Runs at OS level via launchd, costs ~3 sec CPU per cycle, dead silent. Unaffected by Claude sessions opening/closing.

## Configuration reference

### `config/settings.yml`

| Key | Default | Notes |
|---|---|---|
| `daily_cap` | — | DEPRECATED. No longer enforced — pass count to fetch: `fetch 30`. Per-handle cooldown + lifetime cap remain |
| `min_gap_between_publishes_sec` | 90 | Code floor: 30 |
| `voice_match_threshold` | 0.45 | Drafts below this never reach review |
| `min_age_minutes` / `max_age_minutes` | 5 / 90 | Reply window. 5–90 min covers the peak slot (5–35) plus the 30-50%-visibility decay zone (35–90), giving the daemon enough depth to accumulate 30+ candidates per hour |
| `max_subqueries_per_run` | 35 | Hard ceiling on bird calls per fetch (safety net against config drift) |
| `account_or_batch_size` | 9 | OR-batch tracked-account `from:@h1 OR from:@h2 ...` subqueries (X allows ~10 per query) |
| `fetch_cache_ttl_sec` | 300 | Back-to-back fetches within this window reuse the same bird pool — eliminates repeat subqueries |
| `planner.enabled` | `false` | LLM topic-query expansion. Off by default (your manual queries in `topics.yml` are tighter than what the planner produces) |
| `tz` | `UTC` | Target audience TZ, for daily-cap reset |
| `posting_windows` | Tue–Thu 8–11am + 3pm | Research-backed peaks |
| `require_explicit_approval` | `true` | Code refuses to flip this false |
| `banned_terms` | `[]` | Terms that auto-reject any draft containing them (your custom blocklist — competitor names, ex-employer names, etc.) |

### `config/topics.yml` — per-topic filters

| Key | Recommended | Notes |
|---|---|---|
| `min_followers` | 2000 | Excludes the smallest accounts that have no algorithmic distribution |
| `max_followers` | 25000 | Mega-account threads bury your reply; 25K is the Goldilocks ceiling per Vassallo doctrine + Phoenix data |
| `min_engagement_rate` | 0.005 | Below 0.5%, the parent post isn't getting out-of-network distribution — your reply caps at OP's followers |

### `voice-profile.personal.md` and `references/x-overlay.md`

Two files by design:

- **`voice-profile.personal.md`** — *who you are*. Underlying voice DNA. Required, gitignored. Copy from `voice-profile.example.md` and edit. The skill only reads this file (never the example) so a fork's published voice signals don't pollute your drafter prompt or waste tokens.
- **`references/x-overlay.md`** — *platform constraints*. Length floor, opener rotation, banned shapes derived from May 2026 X research. Edit when X behavior changes; don't touch your voice file.

This split lets you tune voice without breaking guardrails, and guardrails without breaking voice.

### `good-drafts.md` — vibe-reference learning loop

Optional but recommended. The skill ships with `good-drafts.example.md`; copy it to `good-drafts.md` (gitignored) and the drafter will start learning from your taste.

**How it works:**

1. During `review`, when you see a draft you love, run `/x-engage good <id>` instead of (or in addition to) `approve`.
2. The skill appends that draft to `good-drafts.md` with auto-timestamp + author tag.
3. On the next `fetch`, `voice.py` reads `good-drafts.md` and injects a **random 3 of N** examples into the drafter prompt as **vibe references only**.
4. The prompt explicitly tells the drafter: *these are mood references, NOT templates to fill in*. The drafter must pick a different T1–T7 template than the examples.
5. A 4-gram overlap lint in `safety.py` rejects any new draft that copies >30% of any example's wording — mechanical guard against the copy-paste failure mode.
6. File auto-trims to the most recent 25 entries (FIFO) — your taste evolves, oldest examples drop.

**Why this won't degrade quality:**

- Few-shot examples are the highest-leverage prompt-engineering technique (per [Anthropic's multishot prompting guide](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/multishot-prompting)). 3–5 examples ≫ 1 example, with diminishing returns past 5–7.
- Random subsetting prevents structure lock-in.
- The 4-gram overlap lint is a deterministic post-draft check — no LLM judgment, fully auditable.
- Falls back gracefully: if `good-drafts.md` doesn't exist, drafter runs unchanged.

You can also create `bad-drafts.md` later for negative examples (anti-patterns the drafter should avoid). Same parser, same gitignore.

## Safety knobs

The following are **hardcoded ceilings** in `references/guardrails.md` and `scripts/lib/config.py`. Config cannot loosen them:

- 25 replies/day absolute panic ceiling
- 30s minimum publish gap
- 12h minimum per-handle cooldown
- 90 min maximum source-post age
- 280 char hard max (X limit)
- 60 char hard min (safety lint rejects shorter drafts as fragments)

Kill switches:

- `X_ENGAGE_HALT=1` env var → halt at any pipeline stage
- `~/.x-engage/PAUSED` file → halt on publish runs
- Any safety signal (captcha, restriction language, suspended account) detected during `publish` → auto-write `PAUSED`, screenshot to `~/Downloads/x-incident-*.png`, exit code 2

### Cookie expiry handling

X session cookies (`AUTH_TOKEN` + `CT0`) expire periodically. The skill detects two failure modes:

1. **Missing cookies** (`.env` empty / `AUTH_TOKEN=` blank): `fetch` and `setup` both halt with a clear message. `setup` shows `[fail] X session cookies missing`.
2. **X explicitly rejects the session** (401/403 in bird's response): `fetch` writes `~/.x-engage/PAUSED` with recovery instructions and exits code 2.

Recovery (whichever path triggered it):
```
1. Open x.com in Chrome → log out → log back in
2. DevTools (Cmd+Opt+I) → Application → Cookies → x.com
3. Copy `auth_token` and `ct0` values
4. Replace AUTH_TOKEN= and CT0= lines in .env
5. rm ~/.x-engage/PAUSED   (only if it exists)
6. /x-engage setup   (verify "[ok] bird authenticated via X")
```

Note: bird gracefully falls back to guest tokens when cookies are technically present but invalid. Search still works (with lower rate limits), so silent expiry won't break the tool — it'll just lose any session-specific advantages.

## Profile-click framing (2026 algo)

Phoenix ranker (X, Jan 2026) weights **profile clicks 12x a like** and uses them as the proxy for "did this reply make someone curious about the replier." Four framing levers in `references/x-overlay.md` constrain reply SHAPE within your existing voice to maximize profile-click-per-impression:

1. **Concrete unit in first 7 words** (T1/T2/T4/T4b/T6 openers must contain $, %, time, count, or ratio). Numbers force "who has this data?" curiosity.
2. **First-person RESOLUTION not problem** for T4/T4b/T6 (`fixed it by cutting the middle step` ✓ vs `had the same problem tbh` ✗). Implies a solved-it artifact lives on the profile.
3. **Insider-framed T3 questions only** (`d1 or d7?` ✓ vs `what's the baseline?` ✗). Triggers the 75–150x OP-reply-back multiplier.
4. **Callback Q close on process/cost/metric topics** instead of trailing ellipsis. Assumption-of-data earns the click.

These are SHAPE rules. Voice (lowercase starts, inline `tbh`/`honestly` fillers, comma splices on purpose, dropped final period on statements, `?` on questions, no quotes, no em-dashes) stays untouched — that's defined in `voice-profile.personal.md`.

## Anti-hallucination guarantees

- The drafter prompt receives **only** the source post text + voice files. No web fetch, no external context. The drafter cannot invent stats, quotes, or handles because it has nothing to invent from.
- Safety lint runs **after** draft generation and rejects anything matching banned shapes (negation-reframe, listicle-wisdom, banned openers, hashtags, URLs, extra @mentions, emoji, dashes, exclamation marks) plus your `banned_terms` from config.
- Voice score gates drafts below `voice_match_threshold` from ever reaching review.
- Publisher refuses to send any draft not explicitly `status='approved'` set by your chat command.

## Architecture

```
scripts/
├── x_engage.py            # CLI orchestrator
└── lib/
    ├── config.py           # .env + YAML loader, panic ceilings, SSL bootstrap
    ├── log.py              # JSON line logger
    ├── fetch.py            # Discovery pipeline (bird → normalize → signals → dedupe)
    ├── fetch_cache.py      # 5-min pool cache + rate-limit cooldown marker
    ├── candidate_pool.py   # SQLite table the background daemon writes to (read by interactive fetch)
    ├── bird_health.py      # Bird auth + rate-limit classifier (401/403 vs 429)
    ├── voice.py            # Claude CLI drafter + heuristic scorer
    ├── safety.py           # Deterministic lint (banned shapes)
    ├── state.py            # SQLite: drafts, cooldowns, seen, openers
    ├── notion_mirror.py    # Notion log (not approval surface)
    ├── publisher.py        # Playwright publish + safety scan
    └── vendor/
        ├── l30d/            # /last30days pipeline (verbatim): bird_x, normalize,
        │                    # signals, dedupe, snippet, relevance, schema, etc.
        └── l30d/vendor/bird-search/   # Node lib that reads X via session cookies
config/
├── *.example.yml           # tracked exemplars
└── *.yml                   # gitignored, your real config
voice-profile.example.md    # generic template (tracked, never loaded)
voice-profile.personal.md   # gitignored — REQUIRED, the only voice file the skill reads
references/x-overlay.md                # X-platform constraints
references/guardrails.md               # hard caps + kill switches
SKILL.md                    # Claude Code skill manifest
```

## Why this exists

The "reply guy strategy" works. Top-performing X accounts in 2025–2026 grew via replies, not original posts (research summary: ~70% time on strategic replies to bigger accounts, ~30% original). But running it manually means 30–60 min/day of disciplined attention better spent building. Existing tools (scheduling-first products like Hypefury, Tweet Hunter, Typefully, Postwise) don't help with the actual reply-composition bottleneck.

`x-engage` automates the bottleneck (drafting + filtering) and keeps the part that should never be automated (judgment) in human hands.

## License

MIT. See [LICENSE](LICENSE).

## Contributing

PRs welcome for:
- Better safety detection patterns (`scripts/lib/safety.py`)
- Locale support beyond English
- Alternative LLM drafter backends (OpenAI, local models)
- Linux/cron scheduling parity

Not welcome:
- Raising the hardcoded panic ceilings
- Removing the chat-approval gate
- Multi-account support

These exist on purpose.

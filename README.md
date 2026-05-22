<p align="center">
  <img src="assets/cover.gif" alt="x-engage — signal · lock · reply in your voice" width="900">
</p>

<h1 align="center">x-engage</h1>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-lightgrey.svg">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude_Code-skill-orange.svg">
</p>

**A curation tool for X, not a reply bot.** x-engage finds the handful of posts in your network worth replying to right now, drafts a response in your voice, and stops there. You read it, edit it, kill it, or ship it. Nothing leaves your machine without you.

x-engage watches a list of accounts and keywords you define, surfaces the small subset of posts worth replying to right now (recency + follower band + engagement velocity), drafts a reply in your voice, and stops. You read it, edit it, or kill it. Then hit publish. That's the whole loop.

The philosophy: replies are only worth sending if you actually mean them. This is a curation tool that respects your judgment, not a reply bot that fakes you. It doesn't help you reply more — it helps you spend less time deciding where to reply at all.

![demo](assets/demo.gif)

## Why x-engage

- **What it does:** Surfaces 5–15 high-signal X posts worth replying to right now, drafts a reply in your voice for each, and waits for you to approve or kill it before anything leaves your machine.
- **What makes it different:** Human-in-the-loop by default. Every reply requires your approval in manual mode (the default). An opt-in **autopilot mode** exists for users who have already calibrated the drafter against their own voice — see the [Autopilot disclaimer](#autopilot-disclaimer) before touching it.

## See the difference

![before/after reply comparison](assets/before-after.gif)

Three rounds of side-by-side: what a generic reply bot would draft vs what x-engage drafts. Lowercase starts, specifics, ask-back questions — versus emojis, "Great insight!", "100%!". The contrast is the whole point.

## x-engage vs alternatives

| | x-engage | ReplyGuyApp / Replier | Manual scrolling |
|---|---|---|---|
| Human approves every reply | Yes (manual mode, default) — opt-in autopilot bypasses approval | No (auto-fires) | Yes |
| Drafts in your voice from a profile file | Yes | Template-driven | N/A |
| Runs discovery in background | Yes (opt-in) | Yes | No |
| Open source | Yes | No | — |
| Free (no subscription) | Yes | $30–80/mo | Free |
| Uses your real X session (no API fees) | Yes | Varies | — |

---

## ⚠️ Before you install — read this

This tool drives a **logged-in browser session** on a real X account via Playwright. X's [automation rules](https://help.x.com/en/rules-and-policies/twitter-automation) prohibit certain automated activity. You are responsible for staying inside them.

- The defaults (15 replies/day, 24h per-handle cooldown, 90-120s jittered gap between publishes, human-typed input, single device fingerprint) are tuned to look like a person who reads X actively for ~25 minutes and replies as they go. They are **not a guarantee** that an account won't be limited.
- The tool ships with **conservative defaults**: 25 replies/day in manual mode, 50/day in autopilot. These caps exist to keep you under X's automation radar — raise them at your own risk.
- Hard caps are enforced in code (`references/guardrails.md`) and **cannot be loosened via config**. Even if `config/settings.yml` says higher, the code clamps to 25 (manual) / 50 (autopilot).
- If you crank volume or run multiple accounts, you will get flagged. Don't.
- Manual mode is the default and the only mode you should run on day one. Autopilot exists, but it is **gated behind a calibration checklist** (see Autopilot disclaimer below). Treat autonomous publishing as a tool you graduate into, not a switch you flip.

### Autopilot disclaimer

Autopilot mode publishes replies to X without per-draft human approval. Before you enable it, you are responsible for completing the following calibration. None of this is optional. If your account gets suspended because you skipped a step, that is on you.

1. **Run manual mode for at least 100 approved replies.** One hundred is the floor, not the target. It is roughly four weeks of normal use at the 25/day cap and gives you a large enough sample to see how the drafter handles edge cases (sarcasm, technical threads, replies to people you disagree with, low-context posts). Fewer than 100 and you are guessing.
2. **Calibrate your voice profile.** `voice-profile.personal.md`, `voice-corpus.md`, and `good-drafts.md` must reflect *your* actual voice, not the defaults shipped in this repo. If a stranger reading 20 of your approved drafts cannot tell them apart from your real posts, you are not done.
3. **Confirm the lint and scoring thresholds are catching off-voice drafts.** Pull a week of manual-mode logs and verify that drafts you rejected scored below threshold and drafts you approved scored above. If the scorer is not separating signal from noise in manual mode, autopilot will publish the noise.
4. **Understand the new ceiling.** Autopilot doubles the daily cap from 25 to 50 replies. That is a deliberate increase in surface area, and it increases your X account suspension risk accordingly. X does not publish its automation thresholds and does not warn before it acts. You are accepting that risk in exchange for unattended operation.

If any of the four are incomplete, keep autopilot off.

If your account is a critical business asset and you're not okay with any incremental risk, use the [official X API](https://docs.x.com/x-api/getting-started/about-x-api) paid tier with write scope instead of Playwright.

---

## What this is (and isn't)

**Is:**
- A signal filter. Pulls only from `accounts.yml` (handles you curated) + `topics.yml` (keywords you defined) — not a firehose
- A follower-band filter. Default 2K–25K: skips mega accounts where your reply is buried, and skips micro accounts where the thread has no audience
- A post-age filter. Default 5–35 min reply window: catches the early-velocity slot where replies get more visibility before the ranker stops feeding the parent
- A drafting assistant. Generates a reply you can approve, redraft with one line of feedback, or kill
- Fully human-gated. Every reply requires your explicit `approve` then `publish`. The code won't let you remove the gate

**Isn't:**
- A mass-reply bot or follower-growth hack
- A DM tool (doesn't touch DMs)
- A scheduler that publishes on your behalf while you sleep
- A scraper of strangers' content — only fetches posts from accounts and topics you explicitly defined
- A guarantee against X flagging your account (see the warning section above)

---

## Quick start

You'll need: macOS, Python 3.10+, Node.js 22+, the [Claude Code](https://claude.ai/code) CLI on PATH, and a logged-in X account.

### 1. Install

```bash
git clone https://github.com/dancolta/x-engage.git
cd x-engage
pip install -r requirements.txt
playwright install chromium
```

### 2. Copy config templates

```bash
cp .env.example .env
cp config/accounts.example.yml config/accounts.yml
cp config/topics.example.yml   config/topics.yml
cp config/settings.example.yml config/settings.yml
cp voice-profile.example.md    voice-profile.personal.md
```

### 3. Add your X session cookies to `.env`

1. Open **x.com** in Chrome, logged in
2. DevTools (Cmd+Opt+I) → **Application** → **Cookies → https://x.com**
3. Copy the values for `auth_token` (~40 chars) and `ct0` (~160 chars)
4. Paste into `.env` as `AUTH_TOKEN=...` and `CT0=...`

No paid API needed. Cookies are read locally and never leave your machine.

### 4. Run the wizard

```bash
/x-engage setup
```

The interactive wizard will walk you through the rest — Playwright login, voice profile customization, optional Notion mirror, and a verification check.

![setup wizard demo](assets/setup-wizard.gif)

---

## Usage

The skill installs as `/x-engage` in Claude Code.

| Command | What it does |
|---|---|
| `/x-engage fetch` | Pull candidates, draft, queue |
| `/x-engage review` | Show all pending drafts in chat |
| `/x-engage approve <ids\|all>` | Mark drafts approved |
| `/x-engage redraft <id> "<feedback>"` | Re-draft one row with your steer |
| `/x-engage kill <id>` | Reject a draft |
| `/x-engage good <id>` | Save a draft as a vibe reference for future runs |
| `/x-engage publish` | Ship approved drafts via Playwright |
| `/x-engage status` | Counts, daily cap, paused state |
| `/x-engage run-bg` | Start the background daemon (10-min scans) |
| `/x-engage stop-bg` | Stop the daemon |
| `/x-engage bg-status` | Daemon state + pool size + last-fetch age |

A typical day:

```
$ /x-engage fetch
fetch: drafted=4, skipped=11, rejected=2, candidates=17

$ /x-engage review
#a1b2c3d4  @builder_42 (12,400 followers) · 8min ago · score 0.91
  Source: "We doubled our revenue in 30 days using only AI."
  Draft:  "What was the baseline though. Doubling from 2k to 4k and from
           200k to 400k are different conversations entirely."

Reply with: approve <ids|all>, redraft <id>: <feedback>, kill <id>, or publish

$ /x-engage approve a1b2c3d4
approve: marked 1 draft(s) approved. Run `/x-engage publish` to ship.

$ /x-engage publish
publish: published=1, failed=0, deferred=0
```

---

## Background daemon

Without the daemon, every `/x-engage fetch` fires ~33 search subqueries live — easy to hit X's 150 req/15 min cookie rate limit. With the daemon, those subqueries run in the background every 10 min, surface candidates into a SQLite pool, and your interactive `/x-engage fetch` just reads from the pool and drafts. 15 drafts in ~3 min instead of 1–2 hours.

```bash
/x-engage run-bg      # install + load launchd plist
/x-engage status      # unified status — includes scan-bg state + pool size
/x-engage stop-bg     # unload (existing pool stays usable)
```

How the split works:

- **Daemon** — Discovery only. Runs filter chain, writes survivors to `candidate_pool` SQLite table. Auto-evicts rows older than 1 hour. Never drafts.
- **Interactive `/x-engage fetch`** — Reads top-scored candidates from the pool, calls the drafter, applies safety lint + voice score, inserts passing drafts into the queue. Falls back to live discovery when pool is empty.

Daemon is opt-in. Default = off. Runs at OS level via launchd, costs ~3 sec CPU per cycle.

![daemon scanning demo](assets/daemon-scan.gif)

---

## Autopilot mode (autonomous publish, opt-in)

> **READ FIRST:** the [Autopilot disclaimer](#autopilot-disclaimer) at the top of this file. Do not enable until you have 100+ manually-approved replies and a calibrated voice profile. If you skip the calibration and your account gets suspended, that is on you.

Autopilot fuses scan → draft → lint → publish into a single loop that runs without per-draft approval. It is a separate code path from manual mode; manual `/x-engage publish` still requires explicit chat approval.

```bash
/x-engage autopilot start                            # uses defaults from settings.yml (or CLI)
/x-engage autopilot start target=25 until=18:00      # pass values inline
/x-engage autopilot start --keep-awake               # also run caffeinate to prevent lid-close sleep
/x-engage autopilot stop                             # unload daemon + kill caffeinate
/x-engage autopilot list                             # today's published replies (audit)
/x-engage status                                     # unified — includes autopilot heartbeat + sleep-block
```

**What it does each tick (every 60s):**

1. Halt checks — `~/.x-engage/PAUSED` flag, daily target hit, `stop_at` reached
2. Pull 1 fresh candidate from the pool (`candidate_max_age_min` window)
3. Draft via the same drafter as manual mode
4. Lint + score — same threshold as manual (`voice_match_threshold`, default 0.45)
5. Insert as approved, publish via Playwright
6. On safety signal — write PAUSED, self-unload daemon, exit

**What it does NOT bypass:**
- 90s min gap between publishes
- Per-handle 24h cooldown
- 4 replies / 30d lifetime cap per author
- Voice-match threshold
- Safety lint
- CAPTCHA / ACCOUNT_PAUSED / RESTRICTION halt

**Resilience contract:**

| Failure | Behavior |
|---|---|
| Process crash | launchd auto-restarts (`KeepAlive` + `ThrottleInterval=30`) |
| Machine reboot | Plist auto-loads on next login via `~/Library/LaunchAgents/` |
| Network blip | Tick logs error, next tick retries in 60s |
| System sleep / lid close | launchd PAUSES — use `--keep-awake` to prevent idle-sleep |
| X cookie expiry | Writes PAUSED, self-unloads — refresh cookies, delete PAUSED, restart |
| X safety signal | Writes PAUSED, screenshot saved, self-unloads |
| New day | Yesterday's daemon self-stopped at `stop_at`. Re-run `autopilot start` manually (intentional gate) |

**Verify it's actually alive (not just installed):** `/x-engage status` shows `heartbeat: Xs ago [ALIVE|STALE|DEAD]`. ALIVE = ticking. STALE (>120s) = check `logs/autopilot.err`. DEAD (>600s) = daemon is wedged.

**Configuration:** see the commented `autopilot:` block in `config/settings.example.yml` — all fields are off by default. Set them in your `config/settings.yml`, or pass via CLI each time. The code clamps `daily_target` to a hard ceiling of 50.

---

## How it works

![filter funnel](assets/filter-funnel.gif)

237 raw posts from your tracked accounts and topic queries → filter chain → drafter → 8 reviewable drafts. The funnel exists so every reply you see has already cleared the recency, follower-band, dedup, and AI-cadence checks. Pipeline detail:

```
accounts.yml + topics.yml
        │
        ▼
discovery pipeline → relevance + freshness + engagement scoring
        │
        ▼
follower-band + age-window + cooldown filters
        │
        ▼
voice-profile.personal.md + x-overlay.md + Claude CLI → draft reply
        │
        ▼
safety lint + voice score → SQLite queue
        │
        ▼
you, in chat: review · approve · redraft · kill
        │
        ▼
Playwright posts to X (headed, humanized)
```

Your `accounts.yml` and `topics.yml` define the input universe. The pipeline queries those handles and keywords, scores each post on relevance + freshness + engagement, enforces filters, deduplicates, and drops everything below threshold. What survives gets a draft generated against your `voice-profile.personal.md`. The discovery pipeline is shared vendored code from another internal skill — same auth model as Playwright posting, zero API cost.

The reply-drafting voice is defined in `voice-profile.personal.md` (gitignored — copy `voice-profile.example.md` to it and edit). `references/x-overlay.md` layers X-specific constraints on top — character minimums, opener rotation, banned spam triggers, constructive-tone requirement.

---

## Configuration

Most users only need to touch a handful of keys. Full reference in [CONFIG.md](CONFIG.md).

| File | What it controls |
|---|---|
| `config/accounts.yml` | Handles you reply to often |
| `config/topics.yml` | Keyword searches mapped to topic buckets |
| `config/settings.yml` | Posting windows, voice-match threshold, banned terms |
| `voice-profile.personal.md` | Your voice DNA (required, gitignored) |
| `references/x-overlay.md` | X-specific constraints (length floor, banned shapes) |
| `good-drafts.md` | Optional — vibe references the drafter learns from |

Most-touched settings:

| Key | Default | Notes |
|---|---|---|
| `voice_match_threshold` | 0.45 | Drafts below this never reach review |
| `min_age_minutes` / `max_age_minutes` | 5 / 90 | Reply window |
| `posting_windows` | Tue–Thu 8–11am + 3pm | Off-peak posts get less reach |
| `banned_terms` | `[]` | Auto-reject any draft containing these (competitor names, etc.) |
| `notion.mirror_enabled` | `false` | Optional Notion log of drafts |

### Voice profile

`voice-profile.example.md` is a generic starter — copy it to `voice-profile.personal.md` and rewrite to match how you actually write. The skill only reads `voice-profile.personal.md`, so the example file is never loaded into prompts.

### Good-drafts learning loop

Optional. When you see a draft you love during `review`, run `/x-engage good <id>` and the skill appends it to `good-drafts.md`. On the next fetch, the drafter sees a random 3-of-N as **vibe references only** (not templates to copy). A 4-gram overlap lint rejects any new draft that copies >30% of an example's wording. Auto-trims to the most recent 25.

---

## Safety knobs

Hardcoded ceilings in `references/guardrails.md` and `scripts/lib/config.py`. Config cannot loosen them:

- 25 replies/day absolute panic ceiling
- 30s minimum publish gap
- 12h minimum per-handle cooldown
- 90 min maximum source-post age
- 280 char hard max (X limit)
- 60 char hard min (safety lint rejects shorter drafts as fragments)

Kill switches:

- `X_ENGAGE_HALT=1` env var → halt at any pipeline stage
- `~/.x-engage/PAUSED` file → halt on publish runs
- Any safety signal (captcha, restriction language, suspended account) during `publish` → auto-write `PAUSED`, screenshot to `~/Downloads/x-incident-*.png`, exit code 2

If your cookies expire, see [Troubleshooting](#troubleshooting).

---

## Anti-hallucination guarantees

- The drafter prompt receives **only** the source post text + your voice files. No web fetch, no external context. The drafter cannot invent stats, quotes, or handles because it has nothing to invent from.
- Safety lint runs **after** draft generation and rejects banned shapes (negation-reframe, listicle-wisdom, banned openers, hashtags, URLs, extra @mentions, emoji, dashes, exclamation marks) plus your `banned_terms`.
- Voice score gates drafts below `voice_match_threshold` from ever reaching review.
- Publisher refuses to send any draft not explicitly `status='approved'` set by your chat command.

---

## FAQ

**Is this allowed under X's TOS?**
X's [automation rules](https://help.x.com/en/rules-and-policies/twitter-automation) prohibit certain automated activity. x-engage is human-gated — every reply requires your explicit approval before publishing — and the defaults (low daily cap, jittered gaps, per-handle cooldown, real browser session) are tuned to stay well inside those rules. That said, no automation is risk-free. Read the warning section above and use judgment. For a critical business account, use the paid X API instead.

**Does it work on Windows/Linux?**
The launchd background daemon is macOS-only. The core CLI works on Linux if you swap launchd for cron or systemd (PRs welcome). Windows is untested — WSL2 should work for the CLI; the headed Playwright login step may need adjustment.

**What if my X cookies expire?**
Re-grab them. Open x.com in Chrome → DevTools → Application → Cookies → x.com → copy `auth_token` and `ct0` into `.env`. If `/x-engage fetch` halts with a 401/403, delete `~/.x-engage/PAUSED` after updating cookies and re-run.

**Can I use this without Notion?**
Yes. Notion is optional and off by default. Set `notion.mirror_enabled: false` in `config/settings.yml` (or leave it unset). Approval happens entirely in chat — Notion is just a searchable log if you want one.

**How do I customize the voice?**
Edit `voice-profile.personal.md`. It's a plain markdown file describing how you write — sentence shape, register, words you do and don't use, examples of replies you'd actually send. The drafter reads it on every run. For X-specific shape rules (length floors, banned openers), edit `references/x-overlay.md` separately so voice and platform constraints stay decoupled.

---

## Troubleshooting

**`bird-search` returns empty results** → Cookies expired. Re-grab `auth_token` and `ct0` from x.com DevTools.

**Publish errored with a captcha screenshot in ~/Downloads** → X flagged the session. Wait 24–48h, log in manually on x.com, then `rm ~/.x-engage/PAUSED` and try again at lower volume.

**Daemon won't start** → Check `bg-status` for error details. Most issues are missing `claude` CLI on PATH or a broken launchd plist (regenerate via `/x-engage run-bg`).

**Drafts feel off** → Your voice profile is the lever. Add 3–5 concrete examples of replies you'd actually send to `voice-profile.personal.md`. The drafter learns far more from examples than from descriptions.

---

## Architecture

```
scripts/
├── x_engage.py            # CLI orchestrator
└── lib/
    ├── config.py           # .env + YAML loader, panic ceilings
    ├── fetch.py            # Discovery pipeline
    ├── fetch_cache.py      # 5-min pool cache + rate-limit cooldown marker
    ├── candidate_pool.py   # SQLite pool the daemon writes to
    ├── voice.py            # Claude CLI drafter + heuristic scorer
    ├── safety.py           # Deterministic lint (banned shapes)
    ├── state.py            # SQLite: drafts, cooldowns, seen, openers
    ├── notion_mirror.py    # Optional Notion log
    ├── publisher.py        # Playwright publish + safety scan
    └── vendor/             # Shared discovery pipeline (vendored)
config/
├── *.example.yml           # tracked exemplars
└── *.yml                   # gitignored, your real config
voice-profile.example.md    # generic starter (tracked, never loaded)
voice-profile.personal.md   # gitignored — REQUIRED
references/x-overlay.md     # X-platform constraints
references/guardrails.md    # hard caps + kill switches
SKILL.md                    # Claude Code skill manifest
```

---

## License

MIT. See [LICENSE](LICENSE).

## Contributing

PRs welcome for:
- Better safety detection patterns (`scripts/lib/safety.py`)
- Locale support beyond English
- Alternative LLM drafter backends (OpenAI, local models)
- Linux/cron and Windows scheduling parity

Not welcome:
- Raising the hardcoded panic ceilings
- Removing the chat-approval gate
- Multi-account support

These exist on purpose.

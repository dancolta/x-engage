# CLAUDE.md

Guidance for Claude Code when working in this repo. Read this before changing anything that touches drafting, voice, or the autopilot loop.

## What this project is

`x-engage` is a **curation tool** for X (Twitter), not a reply bot. It scans a watchlist, surfaces the small subset of posts worth replying to right now, drafts a reply in the user's voice, and queues it for human approval (manual mode) or auto-publishes inside hard safety gates (autopilot mode). All runtime state is local — no cloud, no shared backend.

Two long-form docs explain the why:
- `SKILL.md` — user-facing skill spec (subcommands, examples, autopilot contract).
- `SKILL_DISCIPLINE.md` — **anti-bloat guardrails. Read before adding any rule, lint, or prompt instruction.**

## Architecture in one minute

Drafts come from **corpus retrieval + minimal positive-spec prompt + deterministic post-filter lint**. Not from stacking "don't do X" rules in the prompt.

```
fetch → candidate_pool → voice.draft() → safety.check() → state.insert() → publisher.publish()
              ↑                ↓ Claude CLI     ↓ lint (silent reject)
        scan-bg daemon    voice-profile +  safety.py
        (launchd, 10min)  corpus + receipts (em-dash, aphorism, AI phrases)
```

Key files (don't re-discover these every session):

| File | Role |
|---|---|
| `scripts/x_engage.py` | CLI orchestrator, all `cmd_*` subcommands. 1700+ lines. |
| `scripts/lib/voice.py` | Drafter: retrieves corpus + receipts, invokes Claude CLI. |
| `scripts/lib/safety.py` | Post-filter lint. Hard rules live HERE, not in the prompt. |
| `scripts/lib/state.py` | SQLite queue + cooldown ledger + PAUSED flag check. |
| `scripts/lib/publisher.py` | Playwright publisher. Writes `~/.x-engage/PAUSED` on safety signal. |
| `scripts/lib/candidate_pool.py` | Pool feeder for scan-bg (10-min cron). |
| `voice-profile.personal.md` | Six positive specs. ~80 lines. Don't bloat. |
| `voice-corpus.md` | Tagged reply examples. Top-3 retrieved per draft. |
| `voice-receipts.md` | Static verifiable facts (Dan's GitHub stats, NodeSparks numbers). |
| `config/settings.yml` | Cadence, thresholds, watchlist. See `CONFIG.md` for every key. |

## The Pink Elephant rule (most important)

Telling an LLM "don't use em-dashes" activates the em-dash representation. Every "DON'T" in the prompt re-anchors the model on the forbidden pattern.

- **DO:** add the pattern to `scripts/lib/safety.py` as a post-filter check. Silent rejection, no feedback to the model.
- **DON'T:** add a "things to avoid" bullet to `voice-profile.personal.md` or the drafter prompt.

The voice profile says what the user **does**. The lint catches what slips through.

## When the user flags "not my voice"

Protocol (full version in `SKILL_DISCIPLINE.md`):

1. Identify the specific phrase / shape / register collision.
2. Add to `BANNED_ANYWHERE` (or `BANNED_OPENERS` if position-specific) in `scripts/lib/safety.py`. Comment with date + draft ID.
3. Verify: the failed draft rejects, a clean variant still passes.
4. Kill the draft in the queue (`/x-engage kill <id>`).
5. Run `/x-engage verify`.

Do **not**: add to the prompt, add a new template, lower the voice-match threshold "to give the model more room."

## When the user flags "yes, this is me"

1. `python3 -m scripts.x_engage good <id>` — pins into `good-drafts.md`.
2. If it demonstrates a *new* pattern (new register, new POV, new receipt shape), append manually to `voice-corpus.md` so retrieval picks it up next time.

## Adding rules — the trace test

Before adding any lint entry or voice constraint, answer both:
- **What specific user-rejected draft does this prevent?** (need the draft ID + date + quote)
- **What specific user-approved draft does this enable?**

If you can't name a real draft, the rule is inferred from training-data intuition. **Don't add it.** Wait until a real flagged draft justifies it. Every 30 days, audit lint rules — rules that never fire get deleted.

## Common commands

Entry point is always `python3 -m scripts.x_engage <subcommand>` from the repo root.

```bash
# health
python3 -m scripts.x_engage verify       # skill health check (line counts, bloat, staleness)
python3 -m scripts.x_engage status       # unified snapshot: queue + scan-bg + autopilot + flags

# manual flow
python3 -m scripts.x_engage fetch 15     # draft N candidates (default 15)
python3 -m scripts.x_engage review       # show pending drafts
python3 -m scripts.x_engage approve all
python3 -m scripts.x_engage publish

# autopilot (autonomous, bypasses approval, panic ceiling 50/day)
python3 -m scripts.x_engage autopilot start target=50 until=18:00
python3 -m scripts.x_engage autopilot stop

# pool feeder (auto-started by autopilot; advanced standalone use only)
python3 -m scripts.x_engage run-bg
python3 -m scripts.x_engage stop-bg
```

No formal test suite. `verify` is the closest thing — run it after any change to drafter, lint, voice files, or the CLI.

## Safety contract (don't bypass)

The publisher and autopilot tick check these before every send. Treat as load-bearing:

- `~/.x-engage/PAUSED` exists → halt everything.
- `X_ENGAGE_HALT=1` env var → halt everything.
- 90s minimum gap between publishes.
- Per-handle 24h cooldown.
- 4 replies / 30d lifetime cap per author.
- Voice-match threshold 0.45 (in `config/settings.yml`).
- Autopilot panic ceiling: 50 replies/day. Code refuses higher.

If you see `ACCOUNT_PAUSED`, `RESTRICTION`, `CAPTCHA`, `LOGIN_REQUIRED`, or `COOKIES_EXPIRED` in output, or any command exits with code `2`: **halt immediately, do not retry, surface the screenshot path (`~/Downloads/x-incident-*.png`) to the user.**

## Daemon model

Both daemons run via macOS launchd plists in `~/Library/LaunchAgents/`:

- `com.x-engage.scan-bg` — pool feeder, fires every 10 min. No drafts, no publishes.
- `com.x-engage.autopilot` — autonomous tick every 60s. Drafts, lints, publishes. **Self-unloads** on target hit, `stop_at` time, PAUSED flag, or safety signal.

launchd **pauses on system sleep / lid close.** Lost ticks are not backfilled. The `--keep-awake` flag on `autopilot start` runs `caffeinate -i` for the day to prevent this.

Each new day, autopilot must be re-started manually. This is intentional — it forces a calibration gate.

## Config style

- Personal voice files (`voice-profile.personal.md`, `voice-corpus.md`, `voice-receipts.md`, `good-drafts.md`) are gitignored; `.example` versions are checked in as templates.
- `.env` holds X cookies + optional Notion token. Never commit. `.env.example` shows shape.
- All numeric thresholds live in `config/settings.yml`. Don't hardcode in Python.

## Code conventions

- Python 3.10+, no type-checker enforced but type hints are used throughout `scripts/lib/`.
- Structured logging via `scripts.lib.log` — JSON one-liners to `logs/*.err` for grepability.
- Subcommands print **one-line human summary to stdout** for the skill wrapper to surface in chat. Don't add multi-line UX without checking SKILL.md's "After completion" section.
- Exit codes: `0` success, `1` user error, `2` safety halt (skill wrapper treats this specially).
- No emojis in code or commits unless the user explicitly asks.

## What NOT to do

- Don't add features to the drafter prompt. The prompt is intentionally ~100 lines.
- Don't add "the user dislikes X" instructions anywhere — that's a lint rule.
- Don't lower `voice_match_threshold` or any cooldown to ship more drafts.
- Don't create new templates, registers, or shape steers without a flagged draft justifying it.
- Don't restore anything from `references/_archive/` — those are pre-rebuild legacy files.
- Don't push without running `verify` first if you touched `safety.py`, `voice.py`, or the voice files.

## When in doubt

Read `SKILL_DISCIPLINE.md` end-to-end before adding *any* rule, prompt change, or new file in `scripts/lib/`. It exists because the previous iteration of this skill regressed into a 600-line slop machine, and the rebuild is one careless commit away from doing it again.

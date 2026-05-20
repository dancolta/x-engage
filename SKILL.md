---
name: x-engage
description: Drafts X (Twitter) replies in your voice and queues them for in-chat approval before publishing. Also includes autopilot mode (autonomous scan+draft+publish daemon, no approval, 50/day target, auto-stops at configurable time). Triggers on "/x-engage", "x-engage", "x comment", "reply on x", "draft x replies", "scan x for replies", "review x drafts", "approve x drafts", "publish x replies", "x reply status", "background scan", "run x in background", "stop x daemon", "x background status", "verify x-engage", "x-engage health", "autopilot", "x autopilot", "start autopilot", "stop autopilot", "autopilot status", "run x autonomously".
allowed-tools: Bash
---

# /x-engage

Thin wrapper over the local `x-engage` checkout.

Set `X_ENGAGE_DIR` in your environment (or this skill's caller config) to the absolute path of your local clone. Defaults to `~/Work/x-engage` if unset.

## Architecture (May 2026 rebuild)

Drafts are produced by **corpus retrieval + minimal positive-spec prompt + post-filter lint**, not by stacking rules in the prompt. Key components:

- `voice-profile.personal.md` (~80 lines) — six positive specs + confirmed Dan-voice patterns
- `dan-x-corpus.md` — tagged Dan-voiced reply examples, top-3 retrieved by source-post keyword
- `dan-receipts.md` — static verifiable Dan facts (GitHub stats, NodeSparks numbers), top-2 retrieved by keyword
- `scripts/lib/safety.py` — deterministic post-filter lint (em-dash ban, aphorism patterns, AI-stock phrases)
- `scripts/lib/voice.py` — drafter orchestrator + Claude CLI invocation
- `SKILL_DISCIPLINE.md` — anti-bloat guardrails (read this before adding rules)

Run `/x-engage verify` after any change to catch bloat or staleness early.

## Disambiguation (read before routing)

If the user says vaguely "start the daemon" / "start the bot" / "run x", default to `autopilot start` since it auto-launches the scan-bg pool feeder too — one command covers the full autonomous mode.

Only route to `run-bg` (advanced) if the user explicitly says "**scan only**" / "**pool only**" / "**no publishing**" / "**don't auto-reply**". `run-bg` does NOT publish — it just feeds the pool for later manual `fetch`.

`autopilot start` is a one-way door for the day's account safety. If unsure whether the user wants autonomous publishing vs. manual review, **ASK**.

## Examples

Map user phrasings to subcommands:

- `"/x-engage"` or `"draft some x replies"` or `"scan x"` → `fetch`
- `"draft 30 replies"` or `"fetch 25"` → `fetch 30` / `fetch 25` (count arg)
- `"show me the x queue"` or `"review x drafts"` → `review`
- `"approve 1, 3, 5"` or `"approve all"` → `approve 1,3,5` / `approve all`
- `"redraft 2 shorter, drop the question"` → `redraft 2: shorter, drop the question`
- `"kill #4"` or `"drop draft 4"` → `kill 4`
- `"save #5 as a good one"` or `"mark 5 good"` → `good 5`
- `"ship it"` or `"publish approved"` → `publish`
- `"x status"` or `"how many replies left today"` or `"how is autopilot doing"` or `"is the daemon running"` → `status` (unified — covers queue, scan-bg, autopilot)
- `"verify x-engage"` or `"is the skill healthy"` or `"check for bloat"` → `verify`
- `"start autopilot"` or `"run x autonomously"` or `"autopilot start"` → `autopilot start`  (auto-starts scan-bg)
- `"stop autopilot"` or `"kill autopilot"` → `autopilot stop`
- `"start autopilot target=30 until=17:00"` → `autopilot start target=30 until=17:00`
- `"start autopilot don't sleep"` / `"start autopilot stay awake"` / `"start autopilot keep system on"` → `autopilot start --keep-awake`
- `"show me today's replies"` / `"list published"` / `"what did autopilot send"` → `autopilot list`
- `"show me the last 50 replies"` → `autopilot list 50`
- (advanced) `"start scan-bg only"` / `"pool only no publish"` → `run-bg`
- (advanced) `"stop scan-bg"` → `stop-bg`

## Subcommands

Parse the first word of the user's input as the subcommand, then run the matching command via Bash. All commands start with `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage` — shown abbreviated as `… ` below.

| Subcommand | What it does | Command |
|---|---|---|
| `fetch [N]` (default) | Fetch candidates + score + draft + store in SQLite + mirror to Notion. Optional count: `fetch 30` drafts up to 30 (default 15). | `… fetch [N]` |
| `review` | Show pending drafts inline in chat for the user to act on. | `… review` |
| `approve <ids\|all>` | Mark drafts approved (e.g. `approve 1, 3, 5` or `approve all`). | `… approve <ids>` |
| `redraft <id>: <feedback>` | Re-run drafter for one row with the user's steer (e.g. `redraft 2: shorter, drop the question`). | `… redraft <id> "<feedback>"` |
| `kill <id>` | Reject and remove from queue. | `… kill <id>` |
| `good <id>` | Promote a draft to `good-drafts.md` as a vibe reference. Consider also adding to `dan-x-corpus.md` if it demonstrates a new pattern. | `… good <id>` |
| `publish` | Ship every draft with status=approved via Playwright. | `… publish` |
| `status` | **Unified snapshot** — queue counts, today's published, scan-bg state + pool size, autopilot state + target/stop_at, paused/halt flags. Replaces the old `bg-status` and `autopilot status` (those still work as aliases). | `… status` |
| `setup` | First-time install: verify xurl auth, Notion, claude CLI, log into X via Playwright. | `… setup` |
| `verify` | Skill health check: line counts, lint pattern totals, stale file detection, SKILL.md staleness vs code. Exit 1 if warnings. | `… verify` |
| `autopilot start [target=N] [until=HH:MM]` | Install + load `com.x-engage.autopilot` launchd plist. Daemon ticks every 60s: scan → draft 1 → lint+score → auto-approve → publish via Playwright. **Bypasses manual approval.** **Auto-starts scan-bg** if not running. Stops on target hit, time reached, or safety signal. Defaults: target=50, until=18:00. | `… autopilot start [target=N] [until=HH:MM]` |
| `autopilot stop` | Unload autopilot plist + kill `caffeinate` if active. Pool + queue stay. scan-bg keeps running unless you also `stop-bg`. | `… autopilot stop` |
| `autopilot list [N]` | Print today's published replies (default 20, max 200) — author, score, parent URL, source post, draft text, time. On-demand audit of what shipped. | `… autopilot list [N]` |
| `autopilot start --keep-awake` | Same as `autopilot start` but also runs `caffeinate -i` for the day so the system won't enter idle-sleep when the lid closes. Without this flag, lid-close pauses launchd and ticks stop until wake. | `… autopilot start --keep-awake` |
| **(advanced)** `run-bg` | Install + load scan-bg launchd plist (every 10 min, pool feeder only — no drafts, no publishes). Normally not needed since `autopilot start` auto-launches this. Use only for pool-only / manual workflow. | `… run-bg` |
| **(advanced)** `stop-bg` | Unload scan-bg daemon. Pool stays. | `… stop-bg` |

Stream output to the user. Use long timeout (600000ms) for `fetch` and `publish`.

## Review-phase rendering

When `review` returns rows, render them in this exact format so the user can act fast:

```
#<id>  @<author> (<follower_count> followers) · <age_min>min ago · score <score>
  Source: "<first 140 chars of source post>"
  Draft:  "<draft text>"
```

After listing, prompt:
```
Reply with: approve <ids|all>, redraft <id>: <feedback>, kill <id>, good <id>, or publish
```

**Always end the review response with the Notion DB link** (parsed from `NOTION_DB_ID` in `.env`). The CLI prints it automatically — preserve it.

## After completion

- `fetch`: pulled / drafted / skipped counts. Mention Notion DB URL if mirror is enabled.
- `review`: show drafts as above; do not summarize. Always include the Notion DB link.
- `approve / redraft / kill / good`: confirm action in 1 line ("Approved #1, #3", "Redrafting #2…", "Killed #4", "Saved #5 as vibe reference")
- `publish`: published / failed / deferred counts. Surface any safety signals.
- `status`: phase, today's published count, paused state, queue counts.
- `verify`: relay the report verbatim. If warnings, suggest concrete next action.

## When user flags a draft as "not my voice"

The protocol (full details in `SKILL_DISCIPLINE.md`):

1. **Identify the failure** — which specific phrase / shape / register collision is wrong?
2. **Add to `BANNED_ANYWHERE` (or `BANNED_OPENERS` if position-specific)** in `scripts/lib/safety.py`. Comment with date + draft ID.
3. **Test the lint** — verify the failed draft rejects + a clean Dan-shape variant still passes.
4. **Kill the draft** in the live queue.
5. **Run `/x-engage verify`** to confirm bloat is in check.

Do NOT:
- Add a "don't do this" instruction to the prompt or voice-profile.personal.md (Pink Elephant — re-anchors the model on the forbidden pattern).
- Add a new template, register quota, or shape steer.
- Lower the post-filter threshold to "give the model more room."

## When user flags a draft as "yes, this is me"

1. Run `/x-engage good <id>` — pins into `good-drafts.md`.
2. If the draft demonstrates a NEW pattern (new register, new POV, new receipt shape), also append manually to `dan-x-corpus.md` so future retrieval picks it up.

## References

The references that the drafter actually reads at runtime:

- `dan-x-corpus.md` — tagged Dan-voiced replies. Top-3 retrieved per draft.
- `dan-receipts.md` — verifiable static facts. Top-2 retrieved per draft.
- `voice-profile.personal.md` — six positive specs + anti-pattern reminders.
- `references/guardrails.md` — human-readable rate-limit doc (operational caps, cooldown reasoning). The executable rules are in `scripts/lib/safety.py` + `state.py`.

Anti-bloat: `references/_archive/` holds legacy files from the pre-rebuild architecture (T1-T7 templates etc.). Not loaded. Don't restore.

## Autopilot mode

`/x-engage autopilot start` boots an autonomous loop that drafts AND publishes replies without per-draft approval. Designed for fire-and-forget engagement velocity.

**How it works:**
- launchd plist `com.x-engage.autopilot` fires `autopilot-tick` every 60s
- Each tick: check halt conditions → pull 1 fresh candidate from pool → draft → lint+score (same bar as manual: ≥0.45) → insert as approved → publish via Playwright
- Tick is idempotent — safe to crash and resume
- **Requires `scan-bg` daemon running in parallel** to keep the pool fresh. Autopilot warns if it's not. Start it with `/x-engage run-bg`.
- **Does NOT auto-publish pre-existing pending drafts.** The `pending` queue from manual mode is untouched — autopilot only ships drafts it created in the current tick. To clear a stale manual queue, use `/x-engage review` + `kill` or `approve` + `publish` as normal.

**Stop conditions (any triggers self-unload):**
1. Daily target hit (default 50, panic ceiling 50)
2. `stop_at` time reached (default 18:00 local, uses `tz` from `settings.yml`)
3. `~/.x-engage/PAUSED` flag exists (any safety signal writes this)
4. `X_ENGAGE_HALT=1` env var

**What it does NOT bypass:**
- 90s min gap between publishes
- Per-handle 24h cooldown
- 4 replies / 30d lifetime cap per author
- Voice-match threshold (0.45)
- Safety lint
- CAPTCHA / ACCOUNT_PAUSED / RESTRICTION → writes PAUSED, auto-unloads daemon, exit 2

**Args:**
- `target=N` — override daily target (1 ≤ N ≤ 50). Panic ceiling refuses higher.
- `until=HH:MM` — override stop time (local TZ from settings.yml).

Manual `/x-engage publish` is unaffected — it still requires `require_explicit_approval=true`.

## Resilience contract (what survives what)

| Failure | Behavior | Action needed |
|---|---|---|
| Process crash mid-tick | launchd restarts via `KeepAlive{SuccessfulExit=false}` + retries in ≥30s (`ThrottleInterval`) | None — auto-heals |
| Machine reboot | Plist is in `~/Library/LaunchAgents/` → auto-loads on next login. `RunAtLoad=true` fires immediately. | None — log back in |
| User-account logout | Daemon stops (LaunchAgent runs in user session). Resumes on next login. | None |
| System sleep / lid close | **launchd PAUSES.** Ticks stop. Time spent asleep is LOST (no backfill). | Use `autopilot start --keep-awake` to run `caffeinate -i` and prevent idle-sleep for the day |
| Network blip | Tick exception logged, next tick retries in 60s | None |
| X cookie expiry | Writes PAUSED, self-unloads (`COOKIES_EXPIRED` halt) | Refresh cookies in `.env`, delete PAUSED, re-run `autopilot start` |
| X safety signal | Writes PAUSED, self-unloads. Screenshot in `~/Downloads/x-incident-*.png` | Verify account healthy, delete PAUSED, re-run `autopilot start` |
| New day | Yesterday's daemon self-stopped at `stop_at`. Today's plist isn't loaded. | Re-run `autopilot start` each morning (intentional — enforces calibration gate) |

**How to verify it's actually alive (not just "installed"):** run `/x-engage status` — the `heartbeat: Xs ago [ALIVE]` line proves the tick fired recently. Anything over 120s = STALE = something's wrong; over 600s = DEAD = check `tail logs/autopilot.err`.

## Critical: safety + auth signals

If output contains `ACCOUNT_PAUSED`, `RESTRICTION`, `CAPTCHA`, `LOGIN_REQUIRED`, or exit code 2 (from publish):
- DO NOT retry. Halt.
- Tell the user: "X account safety check failed. Open the screenshot at `~/Downloads/x-incident-*.png`. After confirming the account is healthy, delete `~/.x-engage/PAUSED` to resume."
- Do not run any further X-touching commands until the user explicitly resumes.

If output contains `COOKIES_EXPIRED` (from fetch, exit code 2):
- DO NOT retry. Halt.
- Tell the user: "Your X session cookies expired. To fix:
  1. Open x.com in Chrome, log out, log back in.
  2. DevTools (Cmd+Opt+I) → Application → Cookies → https://x.com
  3. Copy `auth_token` and `ct0` values into `.env` (replace old `AUTH_TOKEN=` and `CT0=` lines).
  4. Delete `~/.x-engage/PAUSED` to resume.
  Then run `/x-engage setup` to verify, and re-run fetch."
- Do not run any further X-touching commands until the user has updated cookies and removed the PAUSED file.

## Unknown args

If arg is not in the table above, print:
```
Usage: /x-engage [fetch|review|approve|redraft|kill|good|publish|status|setup|verify|autopilot]
  fetch [N]      — fetch candidates + draft + queue (default 15)
  review         — show pending drafts in chat
  approve <ids>  — mark drafts approved (e.g. "approve 1, 3" or "approve all")
  redraft <id>   — re-draft one with feedback (e.g. "redraft 2: shorter")
  kill <id>      — reject a draft
  good <id>      — save a draft as a vibe reference for future drafting
  publish        — ship approved drafts via Playwright
  status         — unified snapshot (queue + scan-bg + autopilot + flags)
  setup          — first-time setup
  verify         — skill health check (line counts, bloat, staleness)
  autopilot start [target=N] [until=HH:MM]
                 — autonomous publish daemon (bypasses approval, auto-starts scan-bg)
  autopilot stop — stop autonomous daemon

Advanced (rarely needed — autopilot manages scan-bg automatically):
  run-bg         — install scan-bg pool feeder only (no publishing)
  stop-bg        — unload scan-bg daemon
```

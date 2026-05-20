---
name: x-engage
description: Drafts X (Twitter) replies in your voice and queues them for in-chat approval before publishing. Triggers on "/x-engage", "x-engage", "x comment", "reply on x", "draft x replies", "scan x for replies", "review x drafts", "approve x drafts", "publish x replies", "x reply status", "background scan", "run x in background", "stop x daemon", "x background status", "verify x-engage", "x-engage health".
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
- `"x status"` or `"how many replies left today"` → `status`
- `"start background scan"` or `"run x in background"` → `run-bg`
- `"stop background scan"` → `stop-bg`
- `"background status"` or `"is the daemon running"` → `bg-status`
- `"verify x-engage"` or `"is the skill healthy"` or `"check for bloat"` → `verify`

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
| `status` | Counts, today's published count, cooldown view, paused state. | `… status` |
| `setup` | First-time install: verify xurl auth, Notion, claude CLI, log into X via Playwright. | `… setup` |
| `run-bg` | Install + load a launchd plist so a daemon scans for fresh candidates every 10 min. Next `fetch` pulls from the pre-filled pool. | `… run-bg` |
| `stop-bg` | Unload the daemon. Existing pool stays so any pending `fetch` can still use it. | `… stop-bg` |
| `bg-status` | Show daemon state (running / stopped / not installed) + pool size + last refresh time. | `… bg-status` |
| `verify` | One-shot skill health check: line counts, lint pattern totals, stale file detection, SKILL.md staleness vs code. Exit 1 if warnings. | `… verify` |

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
Usage: /x-engage [fetch|review|approve|redraft|kill|good|publish|status|setup|verify]
  fetch          — fetch candidates + draft + queue (default)
  review         — show pending drafts in chat
  approve <ids>  — mark drafts approved (e.g. "approve 1, 3" or "approve all")
  redraft <id>   — re-draft one with feedback (e.g. "redraft 2: shorter")
  kill <id>      — reject a draft
  good <id>      — save a draft as a vibe reference for future drafting
  publish        — ship approved drafts via Playwright
  status         — counts, published_today, paused state
  setup          — first-time setup
  verify         — skill health check (line counts, bloat, staleness)
  run-bg / stop-bg / bg-status — daemon control
```

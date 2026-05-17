---
name: x-engage
description: Drafts X (Twitter) replies in your voice and queues them for in-chat approval before publishing. Triggers on "/x-engage", "x-engage", "x comment", "reply on x", "draft x replies", "scan x for replies", "review x drafts", "approve x drafts", "publish x replies", "x reply status".
allowed-tools: Bash
---

# /x-engage

Thin wrapper over the local `x-engage` checkout.

Set `X_ENGAGE_DIR` in your environment (or this skill's caller config) to the absolute path of your local clone. Defaults to `~/Work/x-engage` if unset.

## Examples

Map user phrasings to subcommands:

- `"/x-engage"` or `"draft some x replies"` or `"scan x"` → `fetch`
- `"show me the x queue"` or `"review x drafts"` → `review`
- `"approve 1, 3, 5"` or `"approve all"` → `approve 1,3,5` / `approve all`
- `"redraft 2 shorter, drop the question"` → `redraft 2: shorter, drop the question`
- `"kill #4"` or `"drop draft 4"` → `kill 4`
- `"save #5 as a good one"` or `"mark 5 good"` → `good 5`
- `"ship it"` or `"publish approved"` → `publish`
- `"x status"` or `"how many replies left today"` → `status`

## Args

Parse the first word of the user's input as the subcommand:

- `fetch` (or no arg) → fetch candidates + score + draft + store in SQLite + mirror to Notion
- `review` → show pending drafts inline in chat for the user to act on
- `approve <ids|all>` → mark drafts approved (e.g. `approve 1, 3, 5` or `approve all`)
- `redraft <id>: <feedback>` → re-run drafter for one row with the user's steer (e.g. `redraft 2: shorter, drop the question`)
- `kill <id>` → reject and remove from queue
- `good <id>` → promote a draft to `good-drafts.md` as a vibe reference for future drafting (the drafter injects random examples; a 4-gram overlap lint prevents copy-paste outputs)
- `publish` → ship every draft with status=approved via Playwright
- `status` → counts, today's published, daily-cap usage, cooldown view, paused state
- `setup` → first-time install: verify xurl auth, verify Notion, verify claude CLI, log into X via Playwright

## Execution

For each subcommand, run the matching script via Bash:

| Arg | Command |
|---|---|
| `fetch` (default) | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage fetch` |
| `review` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage review` |
| `approve <ids>` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage approve <ids>` |
| `redraft <id>: <feedback>` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage redraft <id> "<feedback>"` |
| `kill <id>` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage kill <id>` |
| `good <id>` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage good <id>` |
| `publish` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage publish` |
| `status` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage status` |
| `setup` | `cd "$X_ENGAGE_DIR" && python3 -m scripts.x_engage setup` |

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

**Always end the review response with the Notion DB link** (parsed from `NOTION_DB_ID` in `.env`, formatted as `https://www.notion.so/<db_id_no_dashes>`). The CLI prints it automatically — preserve it in the rendered output.

## After completion

- `fetch`: pulled / drafted / skipped counts. Mention Notion DB URL if mirror is enabled.
- `review`: show drafts as above; do not summarize. Always include the Notion DB link at the end (CLI prints it automatically).
- `approve / redraft / kill / good`: confirm action in 1 line ("Approved #1, #3", "Redrafting #2…", "Killed #4", "Saved #5 as vibe reference")
- `publish`: published / failed / deferred counts. Surface any safety signals
- `status`: phase, today's count vs cap, paused state, queue counts

## References

Heavy content lives in `references/` and is loaded by the scripts at runtime, not by Claude when this SKILL.md loads:

- `references/x-overlay.md` — X-platform reply rules (T1–T7 templates, length bands, banned openers, Phoenix-ranker tuning). Loaded by `scripts/lib/voice.py` into the drafter prompt.
- `references/guardrails.md` — long-form safety reasoning (account-pause triggers, cookie rotation, posting cadence). Reference doc for humans; the executable rules are in `scripts/lib/safety.py`.

You don't need to read these to invoke the skill — the scripts handle it.

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
Usage: /x-engage [fetch|review|approve|redraft|kill|good|publish|status|setup]
  fetch          — fetch candidates + draft + queue (default)
  review         — show pending drafts in chat
  approve <ids>  — mark drafts approved (e.g. "approve 1, 3" or "approve all")
  redraft <id>   — re-draft one with feedback (e.g. "redraft 2: shorter")
  kill <id>      — reject a draft
  good <id>      — save a draft as a vibe reference for future drafting
  publish        — ship approved drafts via Playwright
  status         — counts, daily cap, paused state
  setup          — first-time setup
```

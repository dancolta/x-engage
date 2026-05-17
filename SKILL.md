---
name: x-comment
description: X (Twitter) reply auto-drafter and chat-approval publisher. Fetches candidate posts from tracked accounts and topic searches via the X API (xurl), drafts replies in your voice via the Claude CLI, and stores them in SQLite + Notion (Notion as log). You approve drafts in-chat via natural-language commands. On `publish`, ships approved drafts via Playwright on a logged-in X session. Triggers on "/x-comment", "x-comment", "x comment", "reply on x", "draft x replies", "scan x for replies", "review x drafts", "approve x drafts", "publish x replies", "x reply status".
---

# /x-comment

Thin wrapper over the local `x-comment` checkout.

Set `X_COMMENT_DIR` in your environment (or this skill's caller config) to the absolute path of your local clone. Defaults to `~/Work/x-comment` if unset.

## Args

Parse the first word of the user's input as the subcommand:

- `fetch` (or no arg) → fetch candidates + score + draft + store in SQLite + mirror to Notion
- `review` → show pending drafts inline in chat for the user to act on
- `approve <ids|all>` → mark drafts approved (e.g. `approve 1, 3, 5` or `approve all`)
- `redraft <id>: <feedback>` → re-run drafter for one row with the user's steer (e.g. `redraft 2: shorter, drop the question`)
- `kill <id>` → reject and remove from queue
- `publish` → ship every draft with status=approved via Playwright
- `status` → counts, today's published, daily-cap usage, cooldown view, paused state
- `setup` → first-time install: verify xurl auth, verify Notion, verify claude CLI, log into X via Playwright

## Execution

For each subcommand, run the matching script via Bash:

| Arg | Command |
|---|---|
| `fetch` (default) | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment fetch` |
| `review` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment review` |
| `approve <ids>` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment approve <ids>` |
| `redraft <id>: <feedback>` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment redraft <id> "<feedback>"` |
| `kill <id>` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment kill <id>` |
| `publish` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment publish` |
| `status` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment status` |
| `setup` | `cd "$X_COMMENT_DIR" && python3 -m scripts.x_comment setup` |

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
Reply with: approve <ids|all>, redraft <id>: <feedback>, kill <id>, or publish
```

## After completion

- `fetch`: pulled / drafted / skipped counts. Mention Notion DB URL if mirror is enabled.
- `review`: show drafts as above; do not summarize
- `approve / redraft / kill`: confirm action in 1 line ("Approved #1, #3", "Redrafting #2…", "Killed #4")
- `publish`: published / failed / deferred counts. Surface any safety signals
- `status`: phase, today's count vs cap, paused state, queue counts

## Critical: safety + auth signals

If output contains `ACCOUNT_PAUSED`, `RESTRICTION`, `CAPTCHA`, `LOGIN_REQUIRED`, or exit code 2 (from publish):
- DO NOT retry. Halt.
- Tell the user: "X account safety check failed. Open the screenshot at `~/Downloads/x-incident-*.png`. After confirming the account is healthy, delete `~/.x-comment/PAUSED` to resume."
- Do not run any further X-touching commands until the user explicitly resumes.

If output contains `COOKIES_EXPIRED` (from fetch, exit code 2):
- DO NOT retry. Halt.
- Tell the user: "Your X session cookies expired. To fix:
  1. Open x.com in Chrome, log out, log back in.
  2. DevTools (Cmd+Opt+I) → Application → Cookies → https://x.com
  3. Copy `auth_token` and `ct0` values into `.env` (replace old `AUTH_TOKEN=` and `CT0=` lines).
  4. Delete `~/.x-comment/PAUSED` to resume.
  Then run `/x-comment setup` to verify, and re-run fetch."
- Do not run any further X-touching commands until the user has updated cookies and removed the PAUSED file.

## Unknown args

If arg is not in the table above, print:
```
Usage: /x-comment [fetch|review|approve|redraft|kill|publish|status|setup]
  fetch          — fetch candidates + draft + queue (default)
  review         — show pending drafts in chat
  approve <ids>  — mark drafts approved (e.g. "approve 1, 3" or "approve all")
  redraft <id>   — re-draft one with feedback (e.g. "redraft 2: shorter")
  kill <id>      — reject a draft
  publish        — ship approved drafts via Playwright
  status         — counts, daily cap, paused state
  setup          — first-time setup
```

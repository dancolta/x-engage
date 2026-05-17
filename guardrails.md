# Guardrails — read this if you're about to touch the code

## Hard caps (don't loosen these, even in config)

| Lever | Default | Panic ceiling (code-enforced) |
|---|---|---|
| Daily publish cap | 10 | 25 |
| Min gap between publishes (intra-batch) | 60s | 30s |
| Per-handle cooldown | 24h | 12h |
| Reply window (source post age) | 5–30 min preferred, 60 min cap | 90 min |
| Max draft length | 280 chars (X limit) | 280 chars |
| Min draft length | 80 chars | 50 chars |

If `config/settings.yml` requests a value worse than the panic ceiling, code uses the panic ceiling and prints a warning.

## Pre-publish account check

Every `publish` run loads `x.com/home` first and scans for restriction language ("Your account is temporarily restricted", "We detected unusual activity", "Verify you're human", captcha challenges). If detected:
- Write `~/.x-comment/PAUSED`
- Screenshot to `~/Downloads/x-incident-<timestamp>.png`
- Exit code 2 with stdout line `ACCOUNT_PAUSED: see screenshot`

## Per-draft filters

**Drafter side (during `fetch`):**
- Skip source post if: < 50 chars, ad, poll, > 60 min old, already-replied author (24h), self-authored, NSFW flag, political-trigger flag, grief/crisis sentiment
- Reject draft if: contains banned opener (`x-overlay.md` list), > 280 chars, < 80 chars, has emoji / `:)` / hashtag / `!`, contains URL, mentions any handle other than OP
- Reject draft if: opener first 4 words match any of last 5 published openers
- Reject draft if: negation-reframe scan hits (see `voice-profile.md`)
- Reject draft if: any term from `banned_terms` in `config/settings.yml` appears in the draft
- Reject draft if: voice-match score < `voice_match_threshold`

**Publisher side (during `publish`):**
- Re-check daily cap → if hit, defer remaining drafts
- Re-check 24h same-author rule (in case you approved 2 for same handle)
- Re-check banned phrases (in case a redraft introduced them)
- Re-check draft is `status=approved` (refuses to publish anything else)

## Kill switches

- `X_COMMENT_HALT=1` env var → instant exit at any pipeline stage
- `~/.x-comment/PAUSED` file → instant exit on publish runs
- 3 publish failures within 1 hour → auto-write PAUSED flag
- Any unexpected modal / captcha during Playwright → screenshot + write PAUSED flag

## Playwright safety

- Single persistent Chromium profile (`~/.x-comment/chrome-profile/`)
- Headed (not headless) to match human session
- Random scroll: 200–600px, 1.5–4s pauses
- Type: 40–120ms/key, 5% chance of pause+correction, never paste
- No proxy, no IP rotation, no profile-dir swapping
- `playwright-stealth` v2.0.2 applied

## After publish

- SQLite: draft row → `status=published`, `published_url` filled, `handles_cooldown` updated
- Notion: mirror row → `status=published`, `published_at` filled
- Log to `logs/publish-<date>.jsonl` (gitignored)

## Daily cap reset

Daily count resets at 00:00 in `config/settings.yml` → `tz` (default `UTC`).

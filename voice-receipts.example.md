# Receipts Bank — Example Template

**Purpose:** Static, verifiable, drop-in receipts the drafter can pull from. When a source post invites a receipt (numbers, named tools, time anchors), the drafter retrieves the top 2 entries matched by keyword overlap.

**Critical:** every receipt must be REAL and VERIFIABLE. The whole point of this file is to replace the AI-invented number-shaped credentials ("~6 months running mcp servers") with concrete facts the drafter can drop in without hallucinating.

**To use:** copy this file to `dan-receipts.md` (gitignored) and replace the example receipts with 15-25 of your own real receipts. Refresh manually every ~30 days — verify every number against a live source before re-saving.

---

## Format

Each receipt:
- `## [NN] [short label]`
- `**topic_keywords:** comma, separated, lowercase` — used by retrieval
- A 1-2 sentence Dan-voiced phrase the drafter can lift or paraphrase
- `**source:** [URL or file]` — where you can verify the claim

The drafter is told these are OPTIONAL real-fact anchors. It MAY use one if it fits the source post. It MUST skip if not. This prevents forced-anchor slop (where the model jams an irrelevant receipt into the reply because the prompt said to).

---

## [01] [example] N public skills shipped this year

**topic_keywords:** skills, shipping, indie, building, public, opensource, ship

shipped N public claude code skills this year, all in `~/.claude/skills` as markdown files, still surprised how much you can do with a single .md plus a prompt

**source:** github.com/YOUR_USERNAME

---

## [02] [example] Year-to-date commit volume

**topic_keywords:** commits, github, velocity, shipping, productivity, output

NN commits this year so far, basically all on tools i open-sourced. before claude code dropped, my github was almost dead

**source:** GitHub search API `q=author:YOUR_USERNAME author-date:>=YYYY-01-01`

---

## [03] [example] Real cost number for an internal tool

**topic_keywords:** outreach, cold email, cost, cheap, automation, api

my outreach pipeline drafts $0.000X per email on gemini-flash. the whole pipeline costs cents and beats $349/mo competitor combined

**source:** github.com/YOUR_USERNAME/YOUR_REPO

---

## [04] [example] Hard-cap-in-code philosophy

**topic_keywords:** automation, safety, cap, guardrails, abuse, rate limit, throttle

hard-capped my linkedin tool at N/day. cap is in code, not config. even if you change the yaml it ignores you. that's the point, the guardrail isn't a setting

**source:** github.com/YOUR_USERNAME/YOUR_REPO

---

# How to populate this file with your own receipts

1. **Run a one-time GitHub stats scan.** Pull your total commits, year-to-date, monthly, top repos, stars, etc. Real numbers only.
2. **Audit your repo READMEs.** Each shipped repo is a receipt opportunity. Extract: what it does in 1 line, the off-round numbers, the design choice that's defensible.
3. **Pull from any business/company copy.** Real customer counts, real revenue if you publish it, real delivery timelines.
4. **Tag aggressively.** The `topic_keywords` list is the retrieval entrypoint. If a keyword feels even loosely relevant, add it — the model gets to choose whether to use the receipt.
5. **Refresh monthly.** Numbers go stale. Set a calendar reminder to re-verify every 30 days.

# What to NOT include

- Invented numbers ("around 100 users" when you have 73 — say 73 or skip).
- Time anchors you can't verify ("6 months ago" when it was actually 4).
- Receipts that name clients without their consent.
- Anything you'd be embarrassed to defend if someone quote-tweets the reply.

Remember: this file's only job is to replace fabricated credentials with verified ones. A smaller, verified bank beats a larger, fuzzy one every time.

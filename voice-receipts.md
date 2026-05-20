# Dan Receipts Bank — Static, Verifiable, Drop-in Anchors

**Built:** 2026-05-20
**Source:** POV bank agent output, cross-referenced against github.com/dancolta + nodesparks.com + local strategy docs
**Refresh cadence:** manual, every ~30 days. Whoever refreshes must verify every number against a live source before re-saving.

**Purpose:** When a source post asks for a receipt, the drafter retrieves from THIS file instead of inventing one. Every entry has a real source. Nothing here is paraphrased opinion — these are concrete, verifiable, Dan-authored facts.

**How the drafter uses this:** at draft-time, the retrieval keyword-matches the source post against the `topic_keywords` tag of each receipt. Top 2 are injected into the prompt as "real facts you MAY draw on if relevant — SKIP if not." The drafter is never forced to use one.

---

## Format

Each receipt:
- `## [NN] [short label]`
- `**topic_keywords:** comma, separated, lowercase` — used by retrieval
- A 1-2 sentence Dan-voiced phrase the drafter can lift or paraphrase
- `**source:** [URL or file]`

---

## [01] 7 public skills shipped in 2026

**topic_keywords:** claude code, skills, shipping, indie, building, public, opensource, ship

shipped 7 public claude code skills this year, all in `~/.claude/skills` as markdown files, still surprised how much you can do with a single .md plus a prompt

**source:** github.com/dancolta — gen-images-skill, seo-drift-monitor, claude-cleanup-skill, trustpilot-outreach-automation, x-engage, linkedin-engage, github-repo-audit (all createdAt in 2026)

---

## [02] 348 commits in 2026 YTD

**topic_keywords:** commits, github, velocity, shipping, productivity, output

348 commits in 2026 so far, basically all on tools i open-sourced. before claude code dropped, my github was almost dead

**source:** GitHub search API `q=author:dancolta author-date:>=2026-01-01`

---

## [03] 84 commits in May alone

**topic_keywords:** commits, shipping, velocity, recent, month, github

84 commits this month and we're not even at the end, mostly on x-engage and linkedin-engage. the leverage from claude code is still uncomfortable to me sometimes

**source:** GitHub search API + per-repo commit counts (May 2026)

---

## [04] 48 commits on x-engage in 3 days

**topic_keywords:** x-engage, build, fast, shipping, weekend, velocity, opensource

48 commits on x-engage in the first 3 days after publishing it, the codebase doubled in the first weekend and i hadn't even told anyone it existed

**source:** github.com/dancolta/x-engage (createdAt 2026-05-17, 48 commits by 2026-05-20)

---

## [05] gen-images-skill 16 stars, top repo

**topic_keywords:** gen-images, image, design, stars, opensource, brand

gen-images-skill is at 16 stars, my most-starred public thing. it's an image-gen skill for claude code that reads your brand voice from existing site copy before drafting prompts

**source:** github.com/dancolta/gen-images-skill (stargazerCount: 16)

---

## [06] Hard-cap-in-code on linkedin-engage

**topic_keywords:** linkedin, automation, safety, cap, guardrails, abuse, rate limit, throttle

hard-capped my linkedin engagement tool at 15/day. cap is in code, not config. even if you change the yaml it ignores you. that's the point, the guardrail isn't a setting

**source:** github.com/dancolta/linkedin-engage README

---

## [07] 14-day same-author cooldown

**topic_keywords:** linkedin, automation, parasocial, cooldown, frequency, spam

linkedin-engage has a 14-day same-author cooldown. anything tighter and the pattern looks robotic to anyone scrolling

**source:** github.com/dancolta/linkedin-engage README behavioral safeguards

---

## [08] Trustpilot outreach cost

**topic_keywords:** outreach, cold email, trustpilot, intent data, scraping, gemini, cost, cheap

my trustpilot outreach drafts cold emails at $0.0003 each on gemini-2.5-flash. the whole pipeline costs cents and beats clay + apollo + lemlist combined for my niche

**source:** github.com/dancolta/trustpilot-outreach-automation README

---

## [09] Trustpilot signal thesis

**topic_keywords:** outreach, intent data, signal, list, trustpilot, cold, prospecting

a 1-star trustpilot review is intent data. free, timestamped, written in the prospect's own words. the list isn't the signal, the public pain is

**source:** github.com/dancolta/trustpilot-outreach-automation README

---

## [10] NodeSparks outreach pipeline numbers

**topic_keywords:** outreach, nodesparks, b2b, sales, pipeline, glue, custom, gtm

my own outreach system is 200 lines of glue code, $15/mo in api credits, generating 10-15 discovery calls a month. closed €30K+ in b2b contracts off it since launch

**source:** application essays + nodesparks.com (Dan-approved verbatim)

---

## [11] NodeSparks delivery model

**topic_keywords:** nodesparks, custom, build, agency, delivery, saas replacement, ownership

we deliver in 2 to 4 weeks. most clients kill 1 to 3 saas subs and get 10 to 15 hours a week back inside the first 30 days. owned codebase, no monthly tax

**source:** nodesparks.com (verbatim)

---

## [12] 2-founder shop, no team

**topic_keywords:** nodesparks, agency, founders, team, senior, junior, outsource

it's 2 founders, no team you've never heard of, one of us is on every project. that's the whole shop. anyone selling you a 50-person ai agency is selling you junior devs in a trench coat

**source:** NodeSparks blog strategy.md + nodesparks.com

---

## [13] No autonomous mode (philosophy)

**topic_keywords:** autonomous, ai agent, automation, human in the loop, philosophy, approval, oversight

there's no autonomous mode on any of my tools. the code refuses to add one. if you want set-it-and-forget-it you're looking at a different product

**source:** github.com/dancolta/x-engage README + linkedin-engage README

---

## [14] README bar = ripgrep / bat

**topic_keywords:** readme, opensource, docs, positioning, github, repo

my readme bar is ripgrep or bat. opinionated, scannable, confident about what it is and what it isn't. saas landing page energy in a readme is a tell

**source:** github.com/dancolta/github-repo-audit README

---

## [15] Cursor cancelled

**topic_keywords:** cursor, ide, claude code, tools, terminal, switch

paid $40 for cursor last month and opened it twice. claude code already lives in my terminal and doesn't make me switch windows

**source:** linkedin-post-generator SKILL.md worked example *(framed as Dan's voice canon — verify before deploying in high-stakes reply)*

---

## [16] SEO-drift product positioning

**topic_keywords:** seo, deploy, regression, monitor, baseline, git, drift

seo-drift-monitor is git for seo. baseline a page, catch the silent regressions your deploys ship. it tracks 13 elements, runs in 4 seconds

**source:** github.com/dancolta/seo-drift-monitor README

---

## [17] Claude-cleanup results

**topic_keywords:** macos, cleanup, disk space, tooling, claude code, skill

claude-cleanup-skill typically frees 2 to 15 gb on a macos box. one command, no risk to your actual files, runs from claude code

**source:** github.com/dancolta/claude-cleanup-skill README

---

## [18] AI tools and the leverage shift

**topic_keywords:** ai, leverage, tools, coding, skills, builder, claude code, productivity

not so long time ago i thought technical skills were the real leverage. past 8-10 months that flipped, the tech stack stopped being the bottleneck. focus, ideas, marketing, distribution and positioning is where the work is now

**source:** Dan voice interview 2026-05-20

---

## [19] Building tool to fix the tool

**topic_keywords:** scraper, automation, linkedin, brittle, debug, self-healing, skill

linkedin scraper broke every few weeks so i wrote a skill that auto-patches it when it does. been running 4 months, i basically just see logs and patches now, zero implication from my side

**source:** Dan voice interview 2026-05-20

---

## [20] Switched fully to Claude Code on Opus 4.5

**topic_keywords:** claude code, n8n, custom, ide, opus, automation, choose tool, build vs no-code

switched fully to claude code since opus 4.5 release. for me writing a custom script for the usecase makes more sense than debugging n8n nodes. for visualisation tho, n8n has no competitors

**source:** Dan voice interview 2026-05-20

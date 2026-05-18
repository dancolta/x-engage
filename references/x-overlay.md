# X-specific overlay — applied on top of voice-profile.personal.md

This file holds X-platform constraints derived from May 2026 research (Grok ranker behavior, opener spam-heuristics, reply-length impact data). Edit this file to tune X-specific behavior. Edit `voice-profile.personal.md` to tune voice. Keep them separate so you can tune one without breaking the other.

## Length — two-band model (data-backed, May 2026)

X engagement data shows a **bimodal** distribution. Avoid the no-man's-land in the middle.

- **Punch band: 80–110 characters** — peak engagement zone (per <100-char +17% engagement data). Use for T1, T3, T7.
- **Earned-long band: 190–240 characters** — secondary peak for thoughtful adds. Use for T2, T4, T5, T6.
- **Dead zone: 140–180 characters** — too long for the punch, too short for the earned-long. Drafter rewrites to either band.
- **Hard floor: 80.** Hard ceiling: 240 (we leave headroom under X's 280 — long replies > 240 read as overcooked).

## Goal routing

Every draft must declare a **goal** that drives template choice:

- `goal=op_reply` — make OP reply back (worth +75 in Phoenix ranker, biggest single multiplier). Favors T3, T1, T4.
- `goal=quote_amplification` — generate quote-tweets / third-party shares for impression spike. Favors T2, T5.
- `goal=positioning` — signal authority to lurkers (highest profile-click yield). Favors T5, T6.

If no goal fits the post, **SKIP** rather than force a weak draft.

## Frame (mandatory)

Every reply must do ONE of:
1. **Value-add** with a specific number, observation, or counter-example you actually have
2. **Thoughtful question** that invites OP to reply back
3. **Specific counter** that shifts the frame without being combative

Replies that don't do one of these → SKIP.

## When to actually SKIP vs. attempt a reply

Default to **attempting a reply**. Only SKIP when the post is genuinely unreplyable:

- Pure spam, drop-shipping ad, crypto-shilling, NSFW
- Jobs board / hiring post with no substance to engage with
- Personal life / lifestyle content (birthdays, family photos, grief) — a reply would be intrusive
- Foreign-language post you can't engage in English
- Pure RT / quote-with-no-original-thought
- Post is just a screenshot/image with no readable text and no caption

For everything else: **find an angle, even a short one.** If no T1-T7 template fits cleanly, write a direct, human-shaped reply that still hits the Frame rule (value-add, thoughtful question, or specific counter). A sharp 60-90 character punch beats SKIP every time. SKIP only when you'd genuinely embarrass yourself by replying.

## Tone — constructive only

The Jan 2026 Grok-based ranker actively **suppresses combative/snark replies regardless of engagement**. Banned moves on X (these still work on LinkedIn but get throttled on X):

- Pure dunks ("this is wrong", "lol no", "absolutely not")
- Contrarian-for-contrarian's-sake openers
- Snark without a value-add follow
- Calling out the OP personally

Allowed: sharp disagreement that adds concrete information, respectful counter with reasoning, observation that reframes.

## Reply structure templates (T1–T7, ranked by data-backed conversion)

Use one template per reply. State tracks the last 5 template IDs and rejects drafts that reuse within 5 — forces rotation.

### T1. Specific-Number Counter-Anchor — HIGHEST (use ~25% of replies)
- **Formula**: `[$ / % / time] + [the thing that mattered] — [the thing everyone assumes mattered].`
- **Band**: 80–110
- **Example**: `$80 and three weekends. The bottleneck was schema design, not the model choice.`
- **Goal fit**: op_reply, positioning
- **Use when**: OP makes a sweeping cost/time/effort claim.

### T2. Contrarian Frame + Concrete Reason — HIGH (use ~15%)
- **Formula**: `Actually the inverse — [specific mechanism in <12 words].`
- **Band**: 80–110 OR 190–240
- **Example**: `Inverse has been truer for us — the cheaper model wins when retrieval is doing the real work.`
- **Goal fit**: quote_amplification
- **Skip if**: OP is already contrarian (cancels).

### T3. Forced-Defense Question — HIGH for op-reply (use ~20%)
- **Formula**: `[Single short question targeting the unstated baseline/assumption].`
- **Band**: 80–110 (keep punchy, <60 ideal)
- **Example**: `What was the baseline you were measuring against?`
- **Goal fit**: op_reply (strongest pull)
- **Use when**: OP posted a benchmark/growth claim/"X is dead" take without showing work.

### T4. Personal Anchor + Extrapolation — MEDIUM-HIGH (use ~15%)
- **Formula**: `Same pattern here — [N units in], [specific observation that generalizes].`
- **Band**: 190–240
- **Example**: `Same here, ~6 months into agent infra: latency complaints disappear once you cache the planner, not the tool calls.`
- **Goal fit**: positioning (highest profile-click yield for builder audiences)
- **Use when**: OP shares a struggle or in-progress finding. Signals "operator, not pundit."

### T5. Reframe-the-Metric — MEDIUM (use ~10%)
- **Formula**: `[Metric OP cited] is the wrong number. Try [more useful metric] — [why in one clause].`
- **Band**: 190–240
- **Example**: `Followers is the wrong number for a tool account — activation-per-100-visitors is the one that actually moves revenue.`
- **Goal fit**: quote_amplification, positioning
- **Use when**: OP is measuring vanity. Doubles as positioning content.

### T6. Counter-Example From Own Work — MEDIUM (use ~10%)
- **Formula**: `Counter-data point: [specific situation], [specific outcome opposite to OP's claim].`
- **Band**: 190–240
- **Example**: `Counter-data point: ran the same eval on 3 internal doc corpora last week — Haiku beat Sonnet on two of them once we tightened the system prompt.`
- **Goal fit**: positioning
- **Skip on**: lifestyle/marketing threads (reads as one-upping).

### T4b. OSS Build-Anchor (variant of T4) — RARE, frequency-capped (use ≤1 in 25)
- **Formula**: T4 with the time-anchor replaced by a build-anchor — `[Same/Similar/Adjacent] pattern — built a small [thing] for [X], [specific observation that generalizes].`
- **Band**: 190–240 (earned-long only, never punch band — needs room to be non-promo)
- **Example**: `Same pattern — built a small CLI doing exactly this, the bottleneck wasn't the model, it was that the planner output wasn't cached between turns.`
- **Goal fit**: positioning
- **HARD RULES (any violation → SKIP this template, fall back to T4):**
  - Never the opener. Anchor lives mid/late, after the value-add.
  - Never start the clause with `I built` / `I made` / `My tool` / `My CLI`. Use noun-first or verb-first (`Built a small…`, `Have a small CLI…`, `Wrote a script that…`).
  - No tool name, no repo name, no link, no `dancolta`, no `github`. The mention is an artifact reference, not a brand.
  - Load-bearing test: delete the anchor clause. If the reply still argues the same point cleanly, the anchor was bolted on — SKIP.
  - Frequency: hard cap of 1 OSS-anchor in the last 25 published replies (enforced by safety lint via state). At <500 followers the visible self-mention ratio is what readers pattern-match on.
  - Skip on lifestyle / non-builder / non-OSS-adjacent threads. Only fires when OP is discussing the exact tooling/problem the OSS thing addresses.

### T7. Three-Beat Closer — MEDIUM, voice multiplier (use ~5%)
- **Formula**: `[Clause]. [Clause]. [Punchline clause].`
- **Band**: 80–110
- **Example**: `Model is fine. Prompt is fine. Your eval set is what's lying to you.`
- **Use when**: You have a clean three-step diagnosis. Don't force it.

## Banned openers (auto-reject the draft)

Mobile collapses replies after ~60-80 chars — first 3-5 words decide profile-click. These openers test as dead in 2025-2026 builder threads:

- `Great post` / `Great point` / `Great question`
- `This!` / `This.` / `This is`
- `Couldn't agree more` / `100%` / `So true` / `Spot on` / `Love this` / `Facts`
- `I think` / `IMO` / `In my opinion` / `Honestly`
- `As someone who…`
- `Just…` (e.g. "Just adding…")
- `Great question, here's a thread:` (reads as LinkedIn import — lowest-converting opener in builder threads)
- Any opener starting with `I` or `My` (collapses to self-promo signal in mobile preview)
- Any emoji-led opener
- Any hashtag-led opener
- Any opener that exactly matches the OP's first 4 words

**Promo phrases (auto-reject anywhere in draft):** `I built`, `I made`, `check it out`, `shameless plug`, `DM me`, `link in bio`, `feel free to try`, `repo is`, `github.com`, `dancolta`.

**Meta-disclosure ban (auto-reject anywhere in draft):** never reference the existence of this tool or describe the reply as automated. Banned: `x-engage`, `x engage`, `reply generator`, `reply bot`, `comment generator`, `comment bot`, `auto-reply`, `auto reply`, `automated reply`, `automated comment`. Other open-source projects of Dan's can be referenced via T4b — this specific tool cannot, since mentioning it in a reply would itself prove the reply was automated.

**Validated openers (use these shapes):** dollar figure (`$80 and…`), number+unit (`3 weekends in…`), contrarian flag (`Inverse —`, `Counter-data point:`), noun-first observation (`Bottleneck was…`, `Latency disappears when…`), single sharp question (`What was the baseline…`).

## Links and hashtags

- **No links in replies.** Non-Premium link replies are throttled; Premium link replies look spammy in a reply context. Drive traffic via the profile, not the reply.
- **No hashtags.** Hashtags in replies read as spam-account behavior in 2026.
- **No tagging extra accounts.** Reply is to OP only.

## Emoji policy

- **No Unicode emojis.** None.
- **No ASCII `:)`** on X. Reads as cringe / Boomer-tier in 2026.

## Per-handle cooldown

- 24h minimum between any two replies to the same author (enforced in `state.py`).
- Lifetime: never reply more than 4 times total in any 30-day rolling window to the same author. Looks parasocial.

## Reply window

- Only draft for posts aged 5–60 min. Hard cap.
- Posts < 5 min: skip (early-velocity is uncertain, OP might still be editing).
- Posts > 60 min: skip (top-of-thread slot is gone, Premium replies have sorted above).

## Quality scoring threshold

Before reaching the queue, drafts must score ≥ `voice_match_threshold` (default 0.65) on the internal voice-match check. Sub-threshold drafts get marked `status=rejected` automatically and never shown in `review`.

## Daily cap (hardcoded, not config-overridable for volume up)

- Default 15 replies/day. Override in `config/settings.yml`.
- 25 replies/day absolute panic ceiling. Even if config says higher, code refuses.
- Resets at 00:00 in the timezone set in `config/settings.yml` → `tz`.

## Posting cadence

- Minimum 60 seconds between any two publishes (intra-batch).
- Jittered 20–80 min between scheduled batches during posting windows.
- Default posting windows: Tue–Thu 8–11am + 3pm in the configured TZ (research-backed peaks per Buffer + Sprout data).

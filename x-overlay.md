# X-specific overlay — applied on top of voice-profile.md

This file holds X-platform constraints derived from May 2026 research (Grok ranker behavior, opener spam-heuristics, reply-length impact data). Edit this file to tune X-specific behavior. Edit `voice-profile.md` (or `voice-profile.personal.md`) to tune voice. Keep them separate so you can tune one without breaking the other.

## Length

- **Minimum: 80 characters.** Replies under 80 chars get less impression weight on X and read as low-effort. Hard floor.
- **Maximum: 280 characters** (X reply limit).
- **Sweet spot: 120–200 characters.** Long enough to add value, short enough to read on mobile in one glance.

## Frame (mandatory)

Every reply must do ONE of:
1. **Value-add** with a specific number, observation, or counter-example you actually have
2. **Thoughtful question** that invites OP to reply back (+75 algorithm weight, Jan 2026 Grok ranker)
3. **Specific counter** that shifts the frame without being combative

Replies that don't do one of these → SKIP.

## Tone — constructive only

The Jan 2026 Grok-based ranker actively **suppresses combative/snark replies regardless of engagement**. Banned moves on X (these still work on LinkedIn but get throttled on X):

- Pure dunks ("this is wrong", "lol no", "absolutely not")
- Contrarian-for-contrarian's-sake openers
- Snark without a value-add follow
- Calling out the OP personally

Allowed: sharp disagreement that adds concrete information, respectful counter with reasoning, observation that reframes.

## Opener rotation (≥5 templates, never repeat opener within 5 replies)

Use one of these opener shapes per reply, rotating across the day:

1. **Direct observation**: `The X framing is doing a lot of heavy lifting here.`
2. **Builder-anchor reply**: `Same here, ~6 months in and…`
3. **Conditional**: `Depends entirely on what stage you're at.`
4. **Specific question**: `What was the baseline though.`
5. **Number-led counter**: `~8 weekends in on a side project, the actual bottleneck was…`
6. **"Borderline" soft accusation**: `The productivity-hack framing is borderline analysis paralysis.`
7. **Three-beat closer leading the reply**: `Shipped it, broke it, redeployed. Different lesson than the post implies.`

The skill tracks the last 5 opener shapes and rejects drafts that reuse.

## Banned openers (auto-reject the draft)

- `Great post`
- `This!`
- `This.`
- `Couldn't agree more`
- `100%`
- `So true`
- `Spot on`
- `Love this`
- `Facts`
- Any emoji-led opener
- Any hashtag-led opener
- Any opener that exactly matches the OP's first 4 words

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

- Default 10 replies/day. Override in `config/settings.yml`.
- 25 replies/day absolute panic ceiling. Even if config says higher, code refuses.
- Resets at 00:00 in the timezone set in `config/settings.yml` → `tz`.

## Posting cadence

- Minimum 60 seconds between any two publishes (intra-batch).
- Jittered 20–80 min between scheduled batches during posting windows.
- Default posting windows: Tue–Thu 8–11am + 3pm in the configured TZ (research-backed peaks per Buffer + Sprout data).

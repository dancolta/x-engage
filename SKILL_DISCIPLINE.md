# Skill Discipline — Anti-Bloat Guardrails

**Built:** 2026-05-20
**Purpose:** Prevent this skill from regressing into the 600-line slop-machine it just got rebuilt from.

The previous voice profile had 185 lines, the drafter prompt stacked 600 lines, and the lint had 20+ rules. Most were either AI-hallucinated (tildes, `borderline X`, `That's it.` as literal phrasing, the filler inventory) or doing more harm than good (filler-starvation steers caused glued-on `tbh`, register-quota nudges caused register collision). The rebuild stripped this back to ~80 lines of voice spec, ~100 lines of drafter prompt, ~12 lint rules — all anchored to the user's actual corpus.

This file is the discipline that keeps it lean.

---

## The 5 anti-bloat rules

### 1. Every new rule must trace to a real flagged failure

Before adding any rule, lint entry, or voice constraint, answer:
- **What specific user-rejected draft does this prevent?**
- **What specific user-approved draft does this enable?**

If you can't name a draft (with the ID, date, and quote), the rule is inferred, not learned. Don't add it.

Examples that pass: `curious` was flagged after draft `#d43660da` opened with "curious what hit the wall first." `stop-and-ask` was flagged after draft `#972b44be` used "stop-and-ask pattern."

Examples that would fail: "AI overuses 'em-dash' so ban semicolons too." No — wait until the user flags an actual semicolon-using draft.

### 2. Rules go in the LINT, never in the PROMPT

The Pink Elephant principle is mechanistically proven: telling the model "don't use em-dashes" activates the em-dash representation. Every "DON'T" line in the prompt re-anchors the model on the forbidden pattern.

- **DO:** add the pattern to `safety.py` post-filter lint. Reject silently, no feedback to the model.
- **DON'T:** add the pattern to `voice-profile.personal.md` as another bullet under "things to avoid."

The voice profile should say what the user DOES, not what he doesn't. The lint catches what slips through.

### 3. New examples go in the corpus, not the prompt

When a new POV, receipt, or voice example appears (the user's voice memo, a new shipped repo, a new flagged "this is me" draft), the move is:

- **DO:** add it to `voice-corpus.md` as a tagged entry. The retrieval picks it up at draft-time when relevant.
- **DON'T:** add it to the prompt as "the user's perspective on X."

The corpus scales linearly. The prompt scales painfully.

### 4. Periodic audit — rules that never fire get deleted

Every 30 days, grep the log for lint rejection reasons:

```
grep "draft_rejected" logs/scan-bg.* | awk -F'"reason": "' '{print $2}' | sort | uniq -c
```

Any rule that has fired ZERO times in 30 days is either:
- (a) Doing its job perfectly — the prompt + corpus + retrieval are preventing the failure mode → safe to delete the lint, the upstream covers it
- (b) Catching nothing because the failure pattern never happens → unused weight → delete

Either way: delete after 30 days of zero hits. If the failure comes back, re-add it then with a new flagged draft as evidence.

### 5. Voice profile target: under 100 lines forever

The voice profile is currently 78 lines. If it grows past 100, something's wrong — usually it's a new "don't" rule that should be in the lint, or a new example that should be in the corpus. Refactor before exceeding the cap.

Hard ceiling: **120 lines**. Past that, the model starts retreating to the safe middle of the rules instead of imitating the corpus.

---

## When the user flags a draft as "not my voice"

The protocol:

1. **Identify the failure** — which specific phrase / shape / register collision is wrong?
2. **Check the corpus** — is there an existing entry that should have steered against this? If yes, the corpus is fine; the lint needs a new entry.
3. **Add to `BANNED_ANYWHERE` (or `BANNED_OPENERS` if position-specific)** in `safety.py`. Comment with date + draft ID.
4. **Test the lint** — run a smoke test against the rejected draft + a clean voice-matched variant to confirm no false positives.
5. **Kill the draft** in the live queue.

Do NOT:
- Add an example of the bad phrase to the voice profile with "don't do this."
- Write a new prompt section explaining the failure to the model.
- Adjust scoring weights or starvation quotas to "discourage" the pattern.

The lint catches it. The corpus + retrieval prevents it. The prompt stays clean.

---

## When the user flags a draft as "yes, this is me"

The protocol:

1. **Run `/x-engage good <id>`** — pins the draft into `good-drafts.md` as a vibe reference (handled by existing code).
2. **Also consider adding to `voice-corpus.md`** if the draft demonstrates a new pattern not already covered (new register, new POV, new receipt shape). Manual edit, tagged like the seed entries.
3. **Do NOT add the draft to the prompt as a positive example.** The corpus is the prompt's positive-example source.

---

## What to NEVER add back

These were tried, failed, and removed during the rebuild. They are AI-hallucinated and re-adding them is reverting the fix:

- Register-starvation block (the "FILLER STARVING — push a `tbh` into this" steer)
- Shape-starvation block (the "3 questions in a row, force a statement" steer)
- T1-T7 template scaffolding (`Counter-data point:`, `Same pattern —`, `Inverse —`)
- Tilde-frequency quota (the user doesn't use tildes — period)
- Filler-frequency quota (fillers happen organically or not at all)
- Lowercase-everywhere mandate (his LinkedIn uses standard caps; X-native lowercase is opener-position only)
- "Borderline X" framing
- "That's it." as a literal phrase
- 3-noun-phrase listicle bans (false positives on legitimate legitimate tricolons)
- Comma-before-and ban (the user's real corpus has both forms)
- Negation-reframe complex regex (his Post 01 ships with `AI isn't the problem / laziness is`)

If any of these come up again as "fixes," the answer is: identify the actual failed draft, add a targeted lint rule, move on. Don't reintroduce the framework.

---

## The North Star

The system works when:
- Voice profile is under 100 lines
- Drafter prompt is under 150 lines (excluding the retrieved corpus block)
- Lint has ~12-15 rules, each tied to a real flagged draft
- Corpus grows to 30+ voice-matched corpus entries
- Drafts feel like the user typed them, not like an AI wearing a hoodie

If any of these inverts (profile bloats, prompt re-stacks, lint hits 30+ rules with vague reasons, corpus stays at 8), pause and refactor before continuing.

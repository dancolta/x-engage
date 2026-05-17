# Good drafts — vibe reference (NOT structural templates)
#
# How this works:
#   - Copy this file to `good-drafts.md` (gitignored, personal).
#   - When `/x-comment review` shows drafts you love, run:
#         /x-comment good <id>
#     The skill appends that draft here with auto-timestamp + template tag.
#   - At draft time, `voice.py` injects a random 3 of N entries into the prompt
#     as **vibe references only**. The drafter is explicitly told NOT to copy
#     structure — only the overall energy/specificity/tone.
#   - A 4-gram overlap lint in `safety.py` rejects any new draft that copies
#     too much from an example (>30% 4-gram overlap → auto-reject + retry).
#   - Rotate naturally: when this file exceeds 25 entries, the oldest is
#     dropped (FIFO). Add `bad-drafts.md` later if you want negative examples.
#
# Each entry uses this format (the `good` command writes it for you):
#
#     ## YYYY-MM-DD · T<n> · re @<author> on <topic>
#     <one-line reply text>
#
# Don't hand-edit unless you really want to. The CLI does the right thing.

## 2026-05-17 · T1 · re @aarondfrancis on Claude Code skills
$80 and three weekends. The bottleneck was schema design, not the model choice.

## 2026-05-18 · T3 · re @gregisenberg on vertical AI
What was the baseline you were measuring against?

## 2026-05-19 · T4 · re @steipete on agent infra latency
Same here, ~6 months into agent infra. Latency complaints disappear once you cache the planner, not the tool calls.

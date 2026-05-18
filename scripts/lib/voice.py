"""Draft generation via the Claude CLI. Voice = voice-profile.personal.md + x-overlay.md.

Scoring is a lightweight heuristic; the LLM does the heavy lifting on tone.
"""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from . import config, log

ROOT = Path(__file__).resolve().parents[2]
VOICE_PROFILE_PERSONAL = ROOT / "voice-profile.personal.md"
VOICE_PROFILE_EXAMPLE = ROOT / "voice-profile.example.md"
X_OVERLAY = ROOT / "references" / "x-overlay.md"
GOOD_DRAFTS = ROOT / "good-drafts.md"

# How many good-draft examples to inject per call (random subset, prevents lock-in)
GOOD_DRAFTS_INJECT_K = 3


def _load_prompt_assets() -> tuple[str, str]:
    """Load the personal voice profile + X overlay.

    `voice-profile.personal.md` is required and gitignored — it holds your actual
    voice. The repo only ships `voice-profile.example.md` as a starter template;
    we never load it (so other users' published voice signals don't pollute the
    drafter prompt or waste tokens).
    """
    if not VOICE_PROFILE_PERSONAL.exists():
        raise FileNotFoundError(
            f"Missing {VOICE_PROFILE_PERSONAL.name}. "
            f"Copy {VOICE_PROFILE_EXAMPLE.name} to {VOICE_PROFILE_PERSONAL.name} "
            f"and edit it with your voice before running fetch."
        )
    return VOICE_PROFILE_PERSONAL.read_text(), X_OVERLAY.read_text()


def _parse_good_drafts(text: str) -> list[str]:
    """Extract reply bodies from good-drafts.md.

    Format: `## YYYY-MM-DD · T<n> · re @<author> on <topic>` header followed by
    one body line. Skip comment lines, headers, and blanks.
    """
    out: list[str] = []
    for header_match in re.finditer(r"(?m)^## .+$", text):
        # Body is the first non-blank, non-comment line after the header
        rest = text[header_match.end():]
        for line in rest.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            out.append(stripped)
            break
    return out


def _load_good_drafts_block() -> str:
    """Return a prompt block with K random good-draft examples, or empty string.

    Examples are framed explicitly as vibe references, NOT structural templates,
    to prevent the drafter from copying sentence shapes.
    """
    if not GOOD_DRAFTS.exists():
        return ""
    try:
        all_examples = _parse_good_drafts(GOOD_DRAFTS.read_text())
    except Exception as e:
        log.warn("good_drafts_parse_failed", error=str(e))
        return ""
    if not all_examples:
        return ""
    sample = random.sample(all_examples, k=min(GOOD_DRAFTS_INJECT_K, len(all_examples)))
    lines = "\n".join(f"- {s}" for s in sample)
    return (
        "# Vibe references — replies Dan previously rated as 'good'\n\n"
        "These show the ENERGY and SPECIFICITY level to aim for. They are NOT "
        "templates to fill in. DO NOT copy any phrase, opener, or sentence shape "
        "from these examples — the safety lint will reject drafts with too much "
        "overlap. Each example uses one of T1-T7. Pick a DIFFERENT template than "
        "any of these examples for your new draft.\n\n"
        f"{lines}\n"
    )


PROMPT_TEMPLATE = """{voice_profile}

---

{x_overlay}

---

{good_drafts_block}

# Source post you are replying to

Author: @{author} ({followers} followers)
Posted: {age_min} minutes ago
Text:
\"\"\"
{source_text}
\"\"\"

{feedback_block}

# Your task

Write ONE X reply in Dan's voice that follows every rule above. Output ONLY the reply text on a single line. No quotes, no preamble, no markdown. If no valid reply is possible, output the literal word SKIP.
"""


def draft_reply(*, source_text: str, author: str, followers: int, age_min: int,
                feedback: str | None = None) -> str:
    """Call the Claude CLI with voice + overlay + source post. Returns raw output."""
    voice, overlay = _load_prompt_assets()
    good_drafts_block = _load_good_drafts_block()
    feedback_block = ""
    if feedback:
        feedback_block = (
            f"# Steer (Dan's feedback on the previous draft — apply this)\n"
            f"\"\"\"\n{feedback}\n\"\"\"\n"
        )
    prompt = PROMPT_TEMPLATE.format(
        voice_profile=voice,
        x_overlay=overlay,
        good_drafts_block=good_drafts_block,
        author=author,
        followers=followers,
        age_min=age_min,
        source_text=source_text,
        feedback_block=feedback_block,
    )

    cli = config.env("CLAUDE_CLI", "claude")
    settings = config.settings().get("drafter") or {}
    model = settings.get("model", "claude-sonnet-4-6")
    cmd = [cli, "--print", "--model", model]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            log.warn("claude_cli_failed", stderr=r.stderr[:300])
            return "SKIP"
        return r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else "SKIP"
    except subprocess.TimeoutExpired:
        log.warn("claude_cli_timeout")
        return "SKIP"
    except FileNotFoundError:
        log.error("claude_cli_not_found", cli=cli)
        return "SKIP"


# --- Scoring ---

OPENER_ANCHORS = (
    "the ", "same here", "depends entirely", "what was", "borderline",
    "shipped", "broke", "been ", "sitting on", "asking for myself",
)


def score_draft(draft: str) -> float:
    """Heuristic voice-match score in [0,1].

    Components:
      - structural fitness (length, sentence count, opener type): up to 0.5
      - idiolect signals (tilde, off-round numbers, 'that's it' / 'asking for myself'): up to 0.3
      - cleanness (no banned shapes already caught by safety; bonus for clean): up to 0.2
    """
    text = draft.strip()
    if not text or text.upper() == "SKIP":
        return 0.0

    score = 0.0

    # Length scoring matches the bimodal bands in x-overlay.md:
    #   Punch band (60–110)       → full points (T1, T3, T7 — concise wins)
    #   Earned-long (190–240)     → full points (T2, T4, T5, T6 — depth wins)
    #   In-between / edge bands   → partial points
    L = len(text)
    if 60 <= L <= 110 or 190 <= L <= 240:
        score += 0.25
    elif 110 < L < 140 or 170 < L < 190:
        score += 0.18
    elif 140 <= L <= 170:
        score += 0.10  # dead-zone — still allowed, just lower priority
    elif 240 < L <= 280:
        score += 0.10

    # Sentence count: 2–3 sentences is the target
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if 2 <= len(sentences) <= 3:
        score += 0.15
    elif len(sentences) == 1 or len(sentences) == 4:
        score += 0.08

    # Opener feels like Dan
    low = text.lower()
    if any(low.startswith(a) for a in OPENER_ANCHORS):
        score += 0.10

    # Idiolect signals
    if "~" in text and re.search(r"~\d", text):
        score += 0.10  # off-round time/count signal
    if re.search(r"\b\d{2,}\b", text) and not re.search(r"\b\d+0+\b", text):
        score += 0.08  # number that doesn't end in zero
    if "borderline" in low:
        score += 0.05
    if "that's it" in low or "asking for myself" in low:
        score += 0.05
    if re.search(r"\([^)]{3,60}\)", text):
        score += 0.05  # parenthetical aside

    # Cleanness bonus (already passed safety lint by the time we score)
    score += 0.20

    return round(min(score, 1.0), 3)

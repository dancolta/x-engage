"""Per-draft safety filters. Enforces voice-profile.md, x-overlay.md, guardrails.md rules
deterministically without LLM judgment so they're auditable.

User-specific banned terms (employer names, ex-clients, taboo topics, etc.) live in
`config/settings.yml` under `banned_terms: []` — loaded lazily so config changes
take effect without a restart.
"""

from __future__ import annotations

import re

BANNED_OPENERS = (
    "great post", "this!", "this.", "couldn't agree more", "100%",
    "so true", "spot on", "love this", "facts",
)

# Negation-reframe scan triggers
NEG_WORDS = re.compile(r"\b(not|isn't|wasn't|aren't|won't)\b", re.IGNORECASE)

# Listicle-wisdom triggers
LISTICLE_PATTERNS = (
    "the most underrated", "the real ", "the actual ", "where most ",
    "tell you everything", "separates", "the screen", "the filter",
    "the test that", "everyone talks about", "where the wheels come off",
)


def _user_banned_terms() -> tuple[str, ...]:
    """Pull `banned_terms` from settings.yml (lowercased)."""
    try:
        from . import config
        terms = config.settings().get("banned_terms") or []
        return tuple(t.lower() for t in terms if isinstance(t, str) and t.strip())
    except Exception:
        return ()

URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
HANDLE_RE = re.compile(r"(?:^|\s)@\w+")
EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F1E6-\U0001F1FF" "]"
)


def lint_draft(draft: str, *, source_author: str, recent_openers: list[str]) -> tuple[bool, str]:
    """Return (passes, reason). reason="" when passes=True.

    Order matters — cheapest checks first so we fail fast.
    """
    text = draft.strip()
    if not text:
        return False, "empty draft"
    if text.upper() == "SKIP":
        return False, "skip token"

    # --- length ---
    if len(text) < 80:
        return False, f"too short ({len(text)} < 80)"
    if len(text) > 280:
        return False, f"too long ({len(text)} > 280)"

    low = text.lower()

    # --- banned openers ---
    for opener in BANNED_OPENERS:
        if low.startswith(opener):
            return False, f"banned opener: {opener!r}"

    # --- emoji / hashtag / handle (other than OP) / link / exclamation ---
    if EMOJI_RE.search(text):
        return False, "contains emoji"
    if " :)" in text or text.startswith(":)") or text.endswith(":)"):
        return False, "ASCII smiley banned on X"
    if HASHTAG_RE.search(text):
        return False, "contains hashtag"
    if "!" in text:
        return False, "exclamation mark banned"
    if "—" in text or "–" in text:
        return False, "em/en dash banned"
    if URL_RE.search(text):
        return False, "contains URL"
    extra_handles = [h.strip().lstrip("@").lower() for h in HANDLE_RE.findall(text)]
    extra_handles = [h for h in extra_handles if h and h != source_author.lower()]
    if extra_handles:
        return False, f"mentions extra handle(s): {extra_handles}"

    # --- negation-reframe scan ---
    if _is_negation_reframe(text):
        return False, "negation-reframe pattern"

    # --- listicle-wisdom ---
    for pat in LISTICLE_PATTERNS:
        if pat in low:
            return False, f"listicle-wisdom: {pat!r}"

    # --- user-defined banlist from config/settings.yml ---
    for pat in _user_banned_terms():
        if pat in low:
            return False, f"banned term: {pat!r}"

    # --- opener uniqueness (first 4 words vs last 5 published) ---
    opener_key = " ".join(text.split()[:4]).lower()
    for prev in recent_openers:
        prev_key = " ".join(prev.split()[:4]).lower()
        if opener_key == prev_key:
            return False, "opener repeats a recent reply"

    return True, ""


def _is_negation_reframe(text: str) -> bool:
    """Detect [negation][period or comma][positive reassertion] pairs.

    Heuristic: if a sentence contains a negation word AND a contrasting clause within
    ~12 words on the other side of a comma/period, flag it.
    """
    if not NEG_WORDS.search(text):
        return False
    # Find any negation followed by a clause-break and a "but"/"it's"/"the X" positive turn
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sent in sentences:
        if not NEG_WORDS.search(sent):
            continue
        # Look for soft-contrast patterns inside one sentence
        if re.search(r"\b(not|isn'?t|wasn'?t|aren'?t|won'?t)\b[^.]{1,60},\s*(it'?s|the|but|just|that'?s)", sent, re.IGNORECASE):
            return True
    # Cross-sentence: negation sentence followed by short positive reassertion
    for i, sent in enumerate(sentences[:-1]):
        nxt = sentences[i + 1]
        if NEG_WORDS.search(sent) and re.match(r"^(it'?s|that'?s|the|but)\b", nxt.strip(), re.IGNORECASE) and len(nxt.split()) <= 12:
            return True
    return False


def extract_opener(text: str) -> str:
    """First sentence (or first 80 chars) of a draft, for history tracking."""
    s = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
    return (s[0] if s else text)[:80]

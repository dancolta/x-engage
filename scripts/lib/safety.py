"""Per-draft safety filters (v2 — pruned May 2026).

Pink Elephant principle: hard rules live HERE (post-filter), not in the drafter
prompt. Telling the model "don't use em-dash" activates the em-dash
representation. We let it draft freely, then reject violators silently.

Operational rate-limits, daily caps, and cooldowns are documented in
`references/guardrails.md` (human-readable) and enforced in this file +
state.py. Keep the doc in sync when changing the constants below.

What we KEEP (confirmed in Dan's real corpus):
- em dashes, en dashes (zero in his real writing)
- exclamation marks (zero in his replies)
- emoji, hashtags, URLs, extra @-mentions
- double quotes, smart quotes (he paraphrases instead)
- promo / meta-disclosure phrases
- aphorism punchline shapes ("X is real, Y is the move", "X is the moat")
- length floor/ceiling
- banned openers ("Great post", "This!", etc.)
- question shape needs `?`
- user-defined banned terms

What we DROPPED (turned out to be AI-hallucinated):
- 3-questions-in-a-row backstop (drafter no longer steered toward questions)
- comma-before-and/or rule (Dan's real corpus has both)
- negation-reframe complex regex (his Post 01 has "AI isn't the problem / laziness is")
- filler count > 1 cap (sometimes natural at emotional peaks)
- OSS-anchor position/frequency cap (corpus handles this naturally)
- listicle-wisdom patterns that weren't actual tells

User-specific banned terms (employer names, ex-clients, taboo topics) live in
`config/settings.yml` under `banned_terms: []`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOOD_DRAFTS = ROOT / "good-drafts.md"
DAN_CORPUS = ROOT / "dan-x-corpus.md"

# Reject draft if its 4-gram overlap with any corpus example exceeds this ratio.
CORPUS_OVERLAP_THRESHOLD = 0.30

BANNED_OPENERS = (
    "great post", "great point", "great question",
    "this!", "this.", "couldn't agree more", "100%",
    "so true", "spot on", "love this", "facts",
    "absolutely", "totally agree",
    # AI register-collision openers (the "tbh-glued-to-formal" failure mode)
    "tbh,", "honestly,", "ngl,",
    # Generic-AI hedge words — Dan-flagged as never-his-voice
    "curious ", "curious,",
)

# Words/phrases banned anywhere in the draft (not just opener).
# These are AI-stock-vocabulary that survive the existing patterns but still
# leak slop into otherwise clean Dan-shape drafts.
#
# GROWTH RULE: only add entries here when Dan explicitly flags a phrase as
# "this is never my voice." Never add inferred or "this sounds AI" guesses
# — that's how the prompt bloated to 600 lines last time. Each entry must
# trace to a specific draft Dan rejected.
BANNED_ANYWHERE = (
    # Generic-AI hedge words (flagged 2026-05-20)
    "curious what", "curious how", "curious if",
    "i'm curious", "im curious",
    # X-and-Y "pattern" / "approach" / "way" cliché construction
    # (flagged 2026-05-20 — "stop-and-ask pattern")
    "stop-and-ask",
    # "X is where it Y" / "X is where the Y" AI-cadence closer
    # (flagged 2026-05-20 — "mixing the two into one file is where it breaks down")
    "is where it ",
    "is where the ",
    "is where things ",
    # Bare-fragment closer after a period — e.g. "...3 paying ones. different math entirely."
    # (flagged 2026-05-20, draft published before lint update.)
    # Shape Dan wants: comma + connector like "that's" before the closer.
    # Pattern is PERIOD-prefixed only, so "..., that's different math entirely"
    # passes while the bare-fragment form rejects.
    ". different math",
    ". whole different game",
    ". different beast",
    ". different game entirely",
    ". wild stuff.",
    # Add more here as Dan flags. Format: lowercased substring match.
)

# Promo / self-promo phrases — auto-reject anywhere in draft.
PROMO_PHRASES = (
    "i built", "i made", "i wrote", "i created", "i shipped",
    "my tool", "my cli", "my script", "my repo", "my project",
    "check it out", "shameless plug", "dm me", "link in bio",
    "feel free to try", "repo is", "github.com", "dancolta",
    # Meta-disclosure bans
    "x-engage", "x engage", "xengage",
    "reply generator", "reply bot", "comment generator", "comment bot",
    "auto-reply", "auto reply", "automated reply", "automated comment",
    # AUTODOC ban (personal-brand surface only — confirmed in voice profile)
    "autodoc", "auto-doc",
    # NodeSparks "we"-framing ban (first-person singular only on X)
    "we at nodesparks", "the team at nodesparks", "our team built",
    "two of us at", "the team and i",
)

# Aphorism-punchline patterns — these survived the voice fingerprint check
# because they're confirmed AI-tells (zero appearances in Dan's real corpus
# and high frequency in Sonnet/GPT outputs).
APHORISM_PATTERNS = (
    # closing-line nouns (standalone clause)
    "is the move", "is the play", "is the answer", "is the whole game",
    "is the only thing", "is the one move", "is the one thing",
    "is the moat", "is the bottleneck", "is the real game",
    # "X is real, ..." comma-chain
    "is real, ", "is real.", "is coming, ", "is coming.",
    "is dead, ", "is dead.",
    # universal-advice closers
    "stop competing", "stop optimizing", "just ship",
)

APHORISM_RE = re.compile(
    r"\b\w+\s+is\s+(real|coming|dead|the\s+(move|play|answer|moat|bottleneck|whole game|one move|one thing|only thing))\b",
    re.IGNORECASE,
)

# Listicle-wisdom — kept only patterns confirmed as AI tells across both the
# X playbook research and the competitor corpus. Pruned heavily — many old
# patterns had too many false positives.
LISTICLE_PATTERNS = (
    "the most underrated", "where most ", "tells you everything",
    "tell you everything", "everyone talks about",
    "where the wheels come off",
    "the combination is the whole story", "that's the whole story",
    "worth a second pass", "worth revisiting",
    "separates the good from", "separates the great from",
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


def _count_tildes(text: str) -> int:
    return text.count("~")


def lint_draft(draft: str, *, source_author: str, recent_openers: list[str],
               recent_drafts: list[str] | None = None) -> tuple[bool, str]:
    """Return (passes, reason). reason="" when passes=True.

    `recent_drafts` is accepted for API compatibility but no longer used —
    the 3-questions-in-a-row backstop was dropped. Variety enforced only by
    opener uniqueness against recent_openers.
    """
    text = draft.strip()
    if not text:
        return False, "empty draft"
    if text.upper() == "SKIP":
        return False, "skip token"

    # --- length ---
    if len(text) < 60:
        return False, f"too short ({len(text)} < 60)"
    if len(text) > 280:
        return False, f"too long ({len(text)} > 280)"

    low = text.lower()

    # --- banned openers ---
    for opener in BANNED_OPENERS:
        if low.startswith(opener):
            return False, f"banned opener: {opener!r}"

    # --- promo / meta-disclosure / NodeSparks-framing phrases ---
    for phrase in PROMO_PHRASES:
        if phrase in low:
            return False, f"promo phrase: {phrase!r}"

    # --- generic-AI stock vocab anywhere in draft ---
    for phrase in BANNED_ANYWHERE:
        if phrase in low:
            return False, f"banned phrase: {phrase!r}"

    # --- emoji / hashtag / link / exclamation / dashes / quotes ---
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
    if '"' in text or "“" in text or "”" in text:
        return False, "double quotes banned"
    if "‘" in text or "’" in text:
        return False, "smart single quotes banned"
    # Straight apostrophe-wrapped phrase ban (catches 'aha moment', 'nobody renting')
    # but allow contractions (don't, it's, that's).
    if re.search(r"(?:^|\s)'[^']{1,40}'(?=\s|[.,!?;:]|$)", text):
        return False, "straight quote-wrapped phrase banned"

    # --- questions must end with '?' ---
    WH_OPENERS = {
        "what", "what's", "whats", "how", "how's", "hows",
        "why", "when", "where", "who", "who's", "whos",
        "which", "whose", "whom",
    }
    AUX_OPENERS = {
        "is", "are", "was", "were", "do", "does", "did",
        "can", "could", "will", "would", "should",
        "have", "has", "had", "am",
    }
    # Subject pronouns/determiners that follow an aux to form an actual question:
    # "did YOU do X?" vs "did THIS the hard way" (statement).
    QUESTION_SUBJECTS = {
        "you", "i", "it", "we", "they", "he", "she",
        "any", "anybody", "anyone", "someone", "everyone",
        "that's", "thats", "your", "their", "our", "his", "her", "my",
    }
    words = text.split()
    first_word = words[0].lower().strip(",.;:") if words else ""
    second_word = words[1].lower().strip(",.;:") if len(words) > 1 else ""
    needs_qmark = False
    trigger_word = ""
    if first_word in WH_OPENERS:
        needs_qmark = True
        trigger_word = first_word
    elif first_word in AUX_OPENERS and second_word in QUESTION_SUBJECTS:
        needs_qmark = True
        trigger_word = f"{first_word} {second_word}"
    if not needs_qmark:
        for clause in re.split(r",\s+", text):
            cw = (clause.split() or [""])[0].lower().strip(",.;:")
            if cw in WH_OPENERS:
                needs_qmark = True
                trigger_word = cw
                break
    if needs_qmark and not text.rstrip().endswith("?"):
        return False, f"question shape ({trigger_word!r}) must end with '?'"

    if URL_RE.search(text):
        return False, "contains URL"
    extra_handles = [h.strip().lstrip("@").lower() for h in HANDLE_RE.findall(text)]
    extra_handles = [h for h in extra_handles if h and h != source_author.lower()]
    if extra_handles:
        return False, f"mentions extra handle(s): {extra_handles}"

    # --- listicle-wisdom (pruned set) ---
    for pat in LISTICLE_PATTERNS:
        if pat in low:
            return False, f"listicle-wisdom: {pat!r}"

    # --- aphorism-punchline (the LLM-philosophy register) ---
    for pat in APHORISM_PATTERNS:
        if pat in low:
            return False, f"aphorism-punchline: {pat!r}"
    if APHORISM_RE.search(text):
        return False, "aphorism-punchline shape"

    # --- tilde cap: 0 is target, 1 grudgingly allowed, 2+ rejected ---
    tilde_count = _count_tildes(text)
    if tilde_count > 1:
        return False, f"too many tildes ({tilde_count}, max 1)"

    # --- user-defined banlist from config/settings.yml ---
    for pat in _user_banned_terms():
        if pat in low:
            return False, f"banned term: {pat!r}"

    # --- opener uniqueness (first 4 words vs recent published) ---
    opener_key = " ".join(text.split()[:4]).lower()
    for prev in recent_openers:
        prev_key = " ".join(prev.split()[:4]).lower()
        if opener_key == prev_key:
            return False, "opener repeats a recent reply"

    # --- corpus overlap (anti-copy lint — applies to Dan corpus, not good-drafts) ---
    overlap_ratio, matched = _max_corpus_overlap(text)
    if overlap_ratio > CORPUS_OVERLAP_THRESHOLD:
        return False, f"copies corpus example ({overlap_ratio:.0%} 4-gram overlap with: {matched[:60]!r})"

    return True, ""


# --- Corpus overlap (anti-copy) ---

_CORPUS_BODIES_CACHE: list[str] | None = None
_CORPUS_BODIES_MTIME: float = 0.0


def _load_corpus_bodies_for_lint() -> list[str]:
    """Cached read of dan-x-corpus.md bodies for overlap-check use."""
    global _CORPUS_BODIES_CACHE, _CORPUS_BODIES_MTIME
    if not DAN_CORPUS.exists():
        _CORPUS_BODIES_CACHE = []
        return []
    mtime = DAN_CORPUS.stat().st_mtime
    if _CORPUS_BODIES_CACHE is not None and mtime == _CORPUS_BODIES_MTIME:
        return _CORPUS_BODIES_CACHE
    bodies: list[str] = []
    try:
        text = DAN_CORPUS.read_text()
        # Match the first `> body` line under each `## [NN] Pattern: ...` header
        for m in re.finditer(r"(?ms)^## \[\d+\] Pattern:.+?\n>\s*(.+?)(?:\n(?!>)|\Z)", text):
            body = re.sub(r"(?m)^> ", "", m.group(1)).strip()
            if body:
                bodies.append(body)
    except Exception:
        bodies = []
    _CORPUS_BODIES_CACHE = bodies
    _CORPUS_BODIES_MTIME = mtime
    return bodies


def _ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    tokens = re.findall(r"\w+", text.lower())
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _max_corpus_overlap(draft: str) -> tuple[float, str]:
    """Return (max 4-gram overlap ratio, matched example body)."""
    examples = _load_corpus_bodies_for_lint()
    if not examples:
        return 0.0, ""
    draft_grams = _ngrams(draft, 4)
    if not draft_grams:
        return 0.0, ""
    best_ratio = 0.0
    best_match = ""
    for ex in examples:
        ex_grams = _ngrams(ex, 4)
        if not ex_grams:
            continue
        shared = draft_grams & ex_grams
        ratio = len(shared) / len(draft_grams)
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = ex
    return best_ratio, best_match


def extract_opener(text: str) -> str:
    """First sentence (or first 80 chars) of a draft, for history tracking."""
    s = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
    return (s[0] if s else text)[:80]

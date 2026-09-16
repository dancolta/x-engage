"""Draft generation via the Claude CLI.

Architecture (v2 — corpus-retrieval, May 2026):
- Minimal positive-spec prompt (no DO-NOT instructions inside the prompt)
- Tag-based retrieval from `voice-corpus.md` — 3 examples picked by source-post pattern
- Hard rules live in `safety.py` post-filter only (Pink Elephant principle)
- Scoring is light: length-band, lexical density, presence of withhold-and-name hook
"""

from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

from . import config, log, safety

ROOT = Path(__file__).resolve().parents[2]
VOICE_PROFILE_PERSONAL = ROOT / "voice-profile.personal.md"
VOICE_PROFILE_EXAMPLE = ROOT / "voice-profile.example.md"
VOICE_CORPUS = ROOT / "voice-corpus.md"
VOICE_RECEIPTS = ROOT / "voice-receipts.md"
GOOD_DRAFTS = ROOT / "good-drafts.md"

# How many corpus examples to inject. Architecture research shows 3-5 is the sweet spot.
CORPUS_INJECT_K = 3

# How many static receipts to inject. Receipts are reference-only — the
# drafter is told it MAY draw on them, not that it must. Two is enough to
# offer choice without overloading the prompt.
RECEIPTS_INJECT_K = 2

# Window for recent-published lookup. Sizes the `recent_drafts` list that
# callers in scripts/x_engage.py pass to the filler cadence gate in safety.py.
# Single source of truth is safety.FILLER_WINDOW. The old shape-starvation
# block that used to read this is gone.
SHAPE_HISTORY_WINDOW = safety.FILLER_WINDOW

# --- Light-tone slot (1-in-5 human-touch beat) ---
#
# Every 5th eligible draft gets a single-line nudge at the bottom of the task
# block that allows a dry, self-deprecating, or deadpan aside if it lands
# naturally. "Eligible" = source post has humor, frustration, or relatable
# builder-pain signals that make a light reply feel earned. Posts about
# pricing, strategy debates, or purely technical claims skip the slot.
_fun_draft_counter: int = 0
_FUN_SLOT_EVERY: int = 5

_FUN_ELIGIBLE_SIGNALS = (
    "lol", "haha", "hah", "funny", "ironic", "irony", "classic", "wild",
    "insane", "crazy", "pain", "broke", "broken", "crashed", "burned",
    "debug", "debugging", "spent", "hours on", "wasted", "again", "still",
    "omg", "wtf", "facepalm", "weekend", "3am", "all night", "give up",
    "giving up", "tried everything", "no idea", "same mistake", "rookie",
    "oops", "turns out", "plot twist", "accidentally", "my bad",
)

_FUN_TASK_NUDGE = (
    "On this draft: if a dry, self-deprecating aside or deadpan observation "
    "lands naturally given the source post (e.g. the recursive irony of building "
    "a tool to fix a tool, a '1 cent for every time' hyperbole, a 'crazy time we "
    "live' beat, a mock-frustrated aside), include it as one inline beat. One beat "
    "only, never as a standalone punchline, never forced. If it doesn't fit the "
    "source post, write it straight. The drafter decides."
)


def _is_fun_eligible(source_text: str) -> bool:
    """Return True if the source post has signals that welcome a light moment."""
    low = source_text.lower()
    return any(sig in low for sig in _FUN_ELIGIBLE_SIGNALS)


# --- Corpus loading ---

def _parse_corpus(text: str) -> list[dict]:
    """Parse voice-corpus.md into entries with body + pattern tags.

    Each entry starts with `## [NN] Pattern: <tag>` header, has a `**Source-post type:**`
    line that we use for retrieval, and a quoted body (starting with `>`).
    Returns list of dicts: {pattern, source_type, body, length}.
    """
    entries: list[dict] = []
    sections = re.split(r"(?m)^## \[\d+\] Pattern: ", text)
    for section in sections[1:]:
        pattern_match = re.match(r"([^\n]+)\n", section)
        if not pattern_match:
            continue
        pattern = pattern_match.group(1).strip()
        src_match = re.search(r"\*\*Source-post type:\*\* ([^\n]+)", section)
        source_type = src_match.group(1).strip() if src_match else ""
        # Body is the first quoted block (starts with > )
        body_match = re.search(r"(?m)^> (.+(?:\n> .+)*)", section)
        if not body_match:
            continue
        body = re.sub(r"(?m)^> ", "", body_match.group(1)).strip()
        entries.append({
            "pattern": pattern,
            "source_type": source_type.lower(),
            "body": body,
            "length": len(body),
        })
    return entries


_CORPUS_CACHE: list[dict] | None = None
_CORPUS_MTIME: float = 0.0
_RECEIPTS_CACHE: list[dict] | None = None
_RECEIPTS_MTIME: float = 0.0


def _load_corpus() -> list[dict]:
    """Cached read of voice-corpus.md."""
    global _CORPUS_CACHE, _CORPUS_MTIME
    if not VOICE_CORPUS.exists():
        log.warn("dan_corpus_missing", path=str(VOICE_CORPUS))
        return []
    mtime = VOICE_CORPUS.stat().st_mtime
    if _CORPUS_CACHE is not None and mtime == _CORPUS_MTIME:
        return _CORPUS_CACHE
    try:
        entries = _parse_corpus(VOICE_CORPUS.read_text())
    except Exception as e:
        log.warn("dan_corpus_parse_failed", error=str(e))
        entries = []
    _CORPUS_CACHE = entries
    _CORPUS_MTIME = mtime
    return entries


# --- Receipts (static facts the user can draw on, never invent) ---

def _parse_receipts(text: str) -> list[dict]:
    """Parse voice-receipts.md into entries with body + keyword tags.

    Each entry starts with `## [NN] <label>`, has a `**topic_keywords:**` line,
    a voice-matched body, and ends with `**source:** ...`.
    Returns: {label, keywords: set, body, source}.
    """
    entries: list[dict] = []
    sections = re.split(r"(?m)^## \[\d+\] ", text)
    for section in sections[1:]:
        # Skip the format example section if it gets matched
        label_match = re.match(r"([^\n]+)\n", section)
        if not label_match:
            continue
        label = label_match.group(1).strip()
        kw_match = re.search(r"\*\*topic_keywords:\*\* ([^\n]+)", section)
        if not kw_match:
            continue
        keywords = {k.strip().lower() for k in kw_match.group(1).split(",") if k.strip()}
        # Body is everything between `**topic_keywords:**` line and `**source:**` line
        body_match = re.search(
            r"\*\*topic_keywords:\*\* [^\n]+\n+(.+?)\n+\*\*source:\*\*",
            section, re.DOTALL,
        )
        if not body_match:
            continue
        body = body_match.group(1).strip()
        source_match = re.search(r"\*\*source:\*\* ([^\n]+)", section)
        source = source_match.group(1).strip() if source_match else ""
        entries.append({
            "label": label,
            "keywords": keywords,
            "body": body,
            "source": source,
        })
    return entries


def _load_receipts() -> list[dict]:
    """Cached read of voice-receipts.md. Empty list if file missing."""
    global _RECEIPTS_CACHE, _RECEIPTS_MTIME
    if not VOICE_RECEIPTS.exists():
        return []
    mtime = VOICE_RECEIPTS.stat().st_mtime
    if _RECEIPTS_CACHE is not None and mtime == _RECEIPTS_MTIME:
        return _RECEIPTS_CACHE
    try:
        entries = _parse_receipts(VOICE_RECEIPTS.read_text())
    except Exception as e:
        log.warn("dan_receipts_parse_failed", error=str(e))
        entries = []
    _RECEIPTS_CACHE = entries
    _RECEIPTS_MTIME = mtime
    return entries


def _retrieve_receipts(source_text: str, k: int = RECEIPTS_INJECT_K) -> list[dict]:
    """Return up to k receipts matched to the source post by keyword overlap.

    Cheap tag-based matching: count how many of each receipt's keywords appear
    in the source post (whole-token match against lowercased source). Top-k
    by overlap. Returns [] if no receipts score > 0 — the drafter writes the
    reply without static-receipt anchors in that case (no forced injection).
    """
    receipts = _load_receipts()
    if not receipts:
        return []
    low = source_text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", low))
    # Also build bigrams so multi-word keywords ("cold email") can match
    words = re.findall(r"[a-z0-9]+", low)
    bigrams = {f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)}

    scored: list[tuple[int, dict]] = []
    for entry in receipts:
        hits = 0
        for kw in entry["keywords"]:
            if " " in kw:
                if kw in bigrams or kw in low:
                    hits += 1
            elif kw in tokens:
                hits += 1
        if hits > 0:
            scored.append((hits, entry))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:k]]


# --- Retrieval ---
#
# Tag-based retrieval. Keyword overlap between source post text and corpus
# entries' source_type tags. Cheap, deterministic, no embedding API call.
# Upgrade path: swap _retrieve_examples() with cosine-similarity over embeddings.

# Keyword → pattern hints. When a source post contains these tokens, boost
# matching corpus entries. Tuned to the 8 seed corpus entries; expand as the
# corpus grows.
RETRIEVAL_KEYWORDS = {
    "cancel": ["saas swap", "cancellation"],
    "cancelled": ["saas swap", "cancellation"],
    "saas": ["saas swap"],
    "subscription": ["saas swap"],
    "claude": ["claude code", "build", "ai tool"],
    "cursor": ["claude code", "build"],
    "n8n": ["choose-the-tool", "automation"],
    "automation": ["scraping problem", "automation"],
    "scraper": ["scraping problem"],
    "scrape": ["scraping problem"],
    "broken": ["scraping problem", "brittle"],
    "break": ["scraping problem", "brittle"],
    "shipped": ["builder velocity", "build"],
    "build": ["build", "builder velocity"],
    "weekend": ["weekend build", "build"],
    "leverage": ["reframing leverage"],
    "moat": ["reframing leverage"],
    "anyone can": ["get-rich-quick"],
    "$50k": ["get-rich-quick"],
    "$50,000": ["get-rich-quick"],
    "agency": ["get-rich-quick", "pricing"],
    "pricing": ["pricing"],
    "expensive": ["pricing"],
    "fiverr": ["pricing"],
    "cheap": ["pricing"],
    "should i use": ["choose-the-tool"],
    "should i build": ["choose-the-tool"],
    "or build from scratch": ["choose-the-tool"],
}


def _retrieve_examples(source_text: str, k: int = CORPUS_INJECT_K,
                       *, allow_filler: bool = True) -> list[dict]:
    """Return up to k corpus entries matched to the source post.

    Strategy:
      1. Score each corpus entry by keyword overlap with source post.
      2. If at least 1 entry scores > 0, take top-k from those.
      3. If nothing matches, fall back to random k from the full corpus
         (the model needs SOMETHING to anchor on, even if it's not topic-matched).

    `allow_filler=False` (the filler budget is spent — see safety.FILLER_WINDOW)
    drops corpus entries containing tbh/kinda from the candidate set, so the
    model isn't shown the pattern it can't use. Falls back to the full corpus
    if filtering would leave fewer than k entries — topic match wins over
    cadence, and the lint is the backstop.
    """
    corpus = _load_corpus()
    if not corpus:
        return []
    if not allow_filler:
        clean = [c for c in corpus if not safety.FILLER_RE.search(c["body"])]
        if len(clean) >= k:
            corpus = clean
    if len(corpus) <= k:
        return corpus

    low = source_text.lower()
    scores: dict[int, int] = {i: 0 for i in range(len(corpus))}
    for kw, hints in RETRIEVAL_KEYWORDS.items():
        if kw not in low:
            continue
        for i, entry in enumerate(corpus):
            for hint in hints:
                if hint in entry["source_type"]:
                    scores[i] += 1

    matched = sorted(
        [(i, s) for i, s in scores.items() if s > 0],
        key=lambda x: -x[1],
    )
    if matched:
        top = [corpus[i] for i, _ in matched[:k]]
        # Fill remaining slots with random non-matched for register diversity
        if len(top) < k:
            unused = [c for c in corpus if c not in top]
            top.extend(random.sample(unused, k=min(k - len(top), len(unused))))
        return top

    return random.sample(corpus, k=k)


# --- Prompt ---

PROMPT_TEMPLATE = """{voice_profile}

---

# the user's real voice corpus (imitate texture, not phrasing)

These are real voice-matched replies. Match the register, the closer rhythm, the comma-splice cadence, the receipt-handling, the open-loop endings. Do NOT lift sentences or phrases verbatim.

{corpus_block}

{receipts_block}

---

# Source post you are replying to

Author: @{author} ({followers} followers)
Posted: {age_min} minutes ago
Text:
\"\"\"
{source_text}
\"\"\"

{feedback_block}

# Your task

Write ONE X reply in the voice defined by the profile above. Apply the six positive specs and imitate the corpus texture. Output ONLY the reply text on a single line. No quotes, no preamble, no markdown. If you cannot produce a voice-matched reply that says something specific, output the literal word SKIP.
{fun_nudge_block}"""


def _format_receipts_block(receipts: list[dict]) -> str:
    """Receipts block — explicit reference-only framing.

    Critical: the model is told these are OPTIONAL real-fact anchors. Never
    forced. The "skip if irrelevant" instruction prevents the forced-anchor
    slop failure mode (where the model jams an irrelevant receipt into the
    reply because the prompt said to use one).
    """
    if not receipts:
        return ""
    lines = ["---", "", "# Real user facts you MAY draw on if relevant (skip if not)",
             "",
             "These are real, verifiable user-authored receipts. Use ONE only if it naturally fits the source post. If none fit, write the reply without referencing them — DO NOT force-insert a receipt. Paraphrase or lift the texture, never copy verbatim.",
             ""]
    for r in receipts:
        lines.append(f"- {r['body']}")
    return "\n".join(lines)


def _format_corpus_block(examples: list[dict]) -> str:
    if not examples:
        return "(no corpus available — fall back to the voice spec only)"
    lines = []
    for ex in examples:
        lines.append(f"**{ex['pattern']}** ({ex['length']} chars)")
        lines.append(f"> {ex['body']}")
        lines.append("")
    return "\n".join(lines).strip()


def draft_reply(*, source_text: str, author: str, followers: int, age_min: int,
                recent_drafts: list[str] | None = None,
                feedback: str | None = None) -> str:
    """Call Claude CLI to produce one reply. Returns raw output or SKIP.

    `recent_drafts` never steers the prompt — the architecture research showed
    that "register starvation" instructions cause register collision. It is
    read for one thing only: if a recent reply already spent the tbh/kinda
    budget, filler-bearing corpus examples are held back from retrieval so the
    model isn't primed to repeat it. The lint gate in safety.py is the backstop.

    `feedback` is the user-side redraft steer when used from `redraft <id>`.
    """
    global _fun_draft_counter

    if not VOICE_PROFILE_PERSONAL.exists():
        raise FileNotFoundError(
            f"Missing {VOICE_PROFILE_PERSONAL.name}. "
            f"Copy {VOICE_PROFILE_EXAMPLE.name} to {VOICE_PROFILE_PERSONAL.name} "
            f"and edit it with your voice before running fetch."
        )

    voice = VOICE_PROFILE_PERSONAL.read_text()
    # Filler budget: spent if any recent reply in the window already used one.
    window = (recent_drafts or [])[:safety.FILLER_WINDOW]
    allow_filler = not any(safety.FILLER_RE.search(prev or "") for prev in window)
    examples = _retrieve_examples(source_text, allow_filler=allow_filler)
    corpus_block = _format_corpus_block(examples)
    receipts = _retrieve_receipts(source_text)
    receipts_block = _format_receipts_block(receipts)

    feedback_block = ""
    if feedback:
        feedback_block = (
            f"# Steer (user feedback on the previous draft — apply this)\n"
            f"\"\"\"\n{feedback}\n\"\"\"\n"
        )

    # --- 1-in-5 light-tone slot ---
    # Increment counter on every draft call (not just eligible ones) so the
    # slot fires at a predictable cadence across the full session, not just
    # within eligible posts.
    _fun_draft_counter += 1
    is_fun_slot = (
        (_fun_draft_counter % _FUN_SLOT_EVERY) == 0
        and _is_fun_eligible(source_text)
        and not feedback  # redraft steers override — user wants something specific
    )
    fun_nudge_block = f"\n{_FUN_TASK_NUDGE}" if is_fun_slot else ""
    if is_fun_slot:
        log.info("fun_slot_active", counter=_fun_draft_counter, author=author)

    prompt = PROMPT_TEMPLATE.format(
        voice_profile=voice,
        corpus_block=corpus_block,
        receipts_block=receipts_block,
        author=author,
        followers=followers,
        age_min=age_min,
        source_text=source_text,
        feedback_block=feedback_block,
        fun_nudge_block=fun_nudge_block,
    )

    cli = config.env("CLAUDE_CLI", "claude")
    settings = config.settings().get("drafter") or {}
    model = settings.get("model", "claude-sonnet-4-6")
    cmd = [cli, "--print", "--model", model]
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            # The CLI prints auth failures ("Not logged in · Please run /login")
            # to stdout, so a stderr-only log reads as an empty mystery.
            log.warn("claude_cli_failed", stderr=r.stderr[:300], stdout=r.stdout[:300])
            return "SKIP"
        return r.stdout.strip().splitlines()[0].strip() if r.stdout.strip() else "SKIP"
    except subprocess.TimeoutExpired:
        log.warn("claude_cli_timeout")
        return "SKIP"
    except FileNotFoundError:
        log.error("claude_cli_not_found", cli=cli)
        return "SKIP"


# --- Shape classification (kept for the 3-questions-in-a-row backstop in safety.py) ---

_DEFAULT_PERSONAL_VERBS = (
    "had", "hit", "ran", "built", "made", "wrote", "shipped", "tried",
    "spent", "saw", "did", "fixed", "broke", "learned", "tested", "been",
    "measured", "cut", "dropped", "killed",
)


def classify_shape(text: str) -> str:
    """Bucket a reply into one of {question, experience, statement}. Cheap heuristic."""
    t = text.strip()
    if not t:
        return "statement"
    if t.endswith("?"):
        return "question"
    head = " ".join(t.split()[:20]).lower()
    pattern = re.compile(rf"\b({'|'.join(_DEFAULT_PERSONAL_VERBS)})\b")
    if pattern.search(head):
        return "experience"
    return "statement"


# --- Scoring ---

def score_draft(draft: str) -> float:
    """Light voice-match score in [0,1].

    The old elaborate heuristic rewarded the wrong signals (tildes, opener
    anchor phrases, listicle-detector misses). The new score is minimal:
      - length-band fit (most important)
      - has at least one specific token (number, $, %, named tool)
      - no obvious slop patterns the lint missed
    Anything voice-shaped should clear the default 0.45 threshold.
    """
    text = draft.strip()
    if not text or text.upper() == "SKIP":
        return 0.0

    score = 0.5  # baseline — already passed lint, assume voice-OK

    # Length band: 110-250 chars is the new sweet spot per 2026 X playbook
    L = len(text)
    if 110 <= L <= 250:
        score += 0.20
    elif 80 <= L < 110 or 250 < L <= 280:
        score += 0.10
    elif L < 80:
        score -= 0.10  # too short to land

    # Specificity tax: at least one concrete token (number, dollar, named tool)
    has_number = bool(re.search(r"\b\d+\b", text))
    has_dollar = "$" in text
    has_proper_noun = bool(re.search(r"\b[A-Z][a-z]+", text))  # weak but cheap
    if has_number or has_dollar:
        score += 0.10
    elif has_proper_noun:
        score += 0.05

    # Withhold-and-name signal: ends with offer or open-loop
    low = text.lower()
    if any(p in low for p in (
        "wrote it up", "wrote a thing", "can share", "if you fancy",
        "happy to break", "let me know", "if it helps", "more details",
    )):
        score += 0.10

    return round(min(max(score, 0.0), 1.0), 3)

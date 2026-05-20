"""Draft generation via the Claude CLI.

Architecture (v2 — corpus-retrieval, May 2026):
- Minimal positive-spec prompt (no DO-NOT instructions inside the prompt)
- Tag-based retrieval from `dan-x-corpus.md` — 3 examples picked by source-post pattern
- Hard rules live in `safety.py` post-filter only (Pink Elephant principle)
- Scoring is light: length-band, lexical density, presence of withhold-and-name hook
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
DAN_CORPUS = ROOT / "dan-x-corpus.md"
DAN_RECEIPTS = ROOT / "dan-receipts.md"
GOOD_DRAFTS = ROOT / "good-drafts.md"

# How many corpus examples to inject. Architecture research shows 3-5 is the sweet spot.
CORPUS_INJECT_K = 3

# How many static receipts to inject. Receipts are reference-only — the
# drafter is told it MAY draw on them, not that it must. Two is enough to
# offer choice without overloading the prompt.
RECEIPTS_INJECT_K = 2

# Window for recent-published lookup. Kept for backward compatibility with
# callers in scripts/x_engage.py — used to populate `recent_openers` for the
# opener-uniqueness lint in safety.py. The old shape-starvation block that
# also used this is gone.
SHAPE_HISTORY_WINDOW = 5


# --- Corpus loading ---

def _parse_corpus(text: str) -> list[dict]:
    """Parse dan-x-corpus.md into entries with body + pattern tags.

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
    """Cached read of dan-x-corpus.md."""
    global _CORPUS_CACHE, _CORPUS_MTIME
    if not DAN_CORPUS.exists():
        log.warn("dan_corpus_missing", path=str(DAN_CORPUS))
        return []
    mtime = DAN_CORPUS.stat().st_mtime
    if _CORPUS_CACHE is not None and mtime == _CORPUS_MTIME:
        return _CORPUS_CACHE
    try:
        entries = _parse_corpus(DAN_CORPUS.read_text())
    except Exception as e:
        log.warn("dan_corpus_parse_failed", error=str(e))
        entries = []
    _CORPUS_CACHE = entries
    _CORPUS_MTIME = mtime
    return entries


# --- Receipts (static facts Dan can draw on, never invent) ---

def _parse_receipts(text: str) -> list[dict]:
    """Parse dan-receipts.md into entries with body + keyword tags.

    Each entry starts with `## [NN] <label>`, has a `**topic_keywords:**` line,
    a Dan-voiced body, and ends with `**source:** ...`.
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
    """Cached read of dan-receipts.md. Empty list if file missing."""
    global _RECEIPTS_CACHE, _RECEIPTS_MTIME
    if not DAN_RECEIPTS.exists():
        return []
    mtime = DAN_RECEIPTS.stat().st_mtime
    if _RECEIPTS_CACHE is not None and mtime == _RECEIPTS_MTIME:
        return _RECEIPTS_CACHE
    try:
        entries = _parse_receipts(DAN_RECEIPTS.read_text())
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


def _retrieve_examples(source_text: str, k: int = CORPUS_INJECT_K) -> list[dict]:
    """Return up to k corpus entries matched to the source post.

    Strategy:
      1. Score each corpus entry by keyword overlap with source post.
      2. If at least 1 entry scores > 0, take top-k from those.
      3. If nothing matches, fall back to random k from the full corpus
         (the model needs SOMETHING to anchor on, even if it's not topic-matched).
    """
    corpus = _load_corpus()
    if not corpus:
        return []
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

# Dan's real voice corpus (imitate texture, not phrasing)

These are real Dan-voiced replies. Match the register, the closer rhythm, the comma-splice cadence, the receipt-handling, the open-loop endings. Do NOT lift sentences or phrases verbatim.

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

Write ONE X reply as Dan. Apply the six positive specs and imitate the corpus texture. Output ONLY the reply text on a single line. No quotes, no preamble, no markdown. If you cannot produce a Dan-shaped reply that says something specific, output the literal word SKIP.
"""


def _format_receipts_block(receipts: list[dict]) -> str:
    """Receipts block — explicit reference-only framing.

    Critical: the model is told these are OPTIONAL real-fact anchors. Never
    forced. The "skip if irrelevant" instruction prevents the forced-anchor
    slop failure mode (where the model jams an irrelevant receipt into the
    reply because the prompt said to use one).
    """
    if not receipts:
        return ""
    lines = ["---", "", "# Real Dan facts you MAY draw on if relevant (skip if not)",
             "",
             "These are real, verifiable Dan-authored receipts. Use ONE only if it naturally fits the source post. If none fit, write the reply without referencing them — DO NOT force-insert a receipt. Paraphrase or lift the texture, never copy verbatim.",
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

    `recent_drafts` is accepted for API compatibility but no longer steers the
    prompt — the architecture research showed that "register starvation"
    instructions cause register collision. Variety is enforced by lint only
    (no 3 questions in a row, opener uniqueness).

    `feedback` is the Dan-side redraft steer when used from `redraft <id>`.
    """
    if not VOICE_PROFILE_PERSONAL.exists():
        raise FileNotFoundError(
            f"Missing {VOICE_PROFILE_PERSONAL.name}. "
            f"Copy {VOICE_PROFILE_EXAMPLE.name} to {VOICE_PROFILE_PERSONAL.name} "
            f"and edit it with your voice before running fetch."
        )

    voice = VOICE_PROFILE_PERSONAL.read_text()
    examples = _retrieve_examples(source_text)
    corpus_block = _format_corpus_block(examples)
    receipts = _retrieve_receipts(source_text)
    receipts_block = _format_receipts_block(receipts)

    feedback_block = ""
    if feedback:
        feedback_block = (
            f"# Steer (Dan's feedback on the previous draft — apply this)\n"
            f"\"\"\"\n{feedback}\n\"\"\"\n"
        )

    prompt = PROMPT_TEMPLATE.format(
        voice_profile=voice,
        corpus_block=corpus_block,
        receipts_block=receipts_block,
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

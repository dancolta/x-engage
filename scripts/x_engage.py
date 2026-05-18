"""x-engage CLI orchestrator. Subcommands: fetch | review | approve | redraft | kill | publish | status | setup.

All subcommands print structured one-line summaries the skill wrapper (SKILL.md)
will surface to Dan in chat. Exit code 2 = account safety signal — caller must HALT.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `from scripts.lib...` work when invoked as `python -m scripts.x_engage`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import config, log, state, voice, safety, notion_mirror
from scripts.lib.fetch import fetch_candidates, CookiesExpired


def _author(item) -> str:
    return (item.author or "").lstrip("@").strip()


def _followers(item) -> int:
    eng = item.engagement or {}
    for k in ("followers", "author_followers", "follower_count"):
        if k in eng:
            try:
                return int(eng[k] or 0)
            except (TypeError, ValueError):
                continue
    return 0


# --- Helpers ---

def _check_halted() -> None:
    if config.is_halted():
        print("HALTED: kill switch engaged (X_ENGAGE_HALT=1 or ~/.x-engage/PAUSED)")
        sys.exit(2)


def _settings_or_panic() -> dict:
    s = config.settings()
    s["daily_cap"] = config.safe_int(s.get("daily_cap", 15), 15, 1, config.PANIC["daily_cap_max"])
    s["min_gap_between_publishes_sec"] = config.safe_int(
        s.get("min_gap_between_publishes_sec", 90), 90,
        lower=config.PANIC["min_gap_sec_floor"], upper=3600,
    )
    s["voice_match_threshold"] = float(s.get("voice_match_threshold", 0.45))
    s["handle_cooldown_hours"] = config.safe_int(
        s.get("handle_cooldown_hours", 24), 24,
        lower=config.PANIC["handle_cooldown_hours_floor"], upper=168,
    )
    return s


# --- fetch ---

def cmd_fetch() -> int:
    _check_halted()
    settings = _settings_or_panic()
    threshold = settings["voice_match_threshold"]

    counts = state.queue_counts()
    pending = counts.get("pending", 0)
    daily_cap = settings["daily_cap"]
    published_today = state.count_published_today()
    capacity = daily_cap - published_today - pending
    if capacity <= 0:
        print(f"fetch: daily capacity full (cap={daily_cap}, published_today={published_today}, pending={pending}). Skipping.")
        return 0

    log.info("fetch_start", capacity=capacity)
    try:
        candidates = fetch_candidates()
    except CookiesExpired as e:
        print(f"COOKIES_EXPIRED: {e}")
        print("Fix: log out + back in on x.com, copy fresh auth_token + ct0 from")
        print("DevTools (Application → Cookies → x.com) into .env, then delete")
        print(f"{Path.home() / '.x-engage' / 'PAUSED'} to resume.")
        return 2
    log.info("candidates_count", n=len(candidates))

    drafted = 0
    skipped = 0
    rejected = 0
    recent_openers = state.recent_openers(limit=5)

    for item in candidates:
        if drafted >= capacity:
            break
        state.mark_seen(item.item_id)
        author = _author(item)
        followers = _followers(item)
        age_min = int(item.metadata.get("age_min") or 0)
        source_text = item.body or item.title or ""

        if state.lifetime_replies_to(author.lower(), within_days=30) >= 4:
            skipped += 1
            continue

        draft = voice.draft_reply(
            source_text=source_text,
            author=author,
            followers=followers,
            age_min=age_min,
        )
        # SKIP retry: drafter sometimes plays it too safe and emits SKIP on
        # posts that DO warrant a reply. Re-ask once with an explicit nudge
        # before giving up. Single retry caps cost (~one extra Claude CLI call).
        if draft.strip().upper() == "SKIP" or not draft.strip():
            retry_hint = (
                "The previous attempt returned SKIP. Look again — is there ANY "
                "reasonable, specific reply you can write here? Even a short "
                "punchy question or a single observation counts if it adds "
                "something concrete. Only SKIP if the post is genuinely "
                "unreplyable (pure spam, jobs board, foreign language, "
                "lifestyle/personal content where a reply would be intrusive)."
            )
            draft = voice.draft_reply(
                source_text=source_text,
                author=author,
                followers=followers,
                age_min=age_min,
                feedback=retry_hint,
            )
            if draft.strip().upper() == "SKIP" or not draft.strip():
                log.info("draft_skip_after_retry", tweet_id=item.item_id, author=author)
                skipped += 1
                continue
            log.info("draft_recovered_after_retry", tweet_id=item.item_id)

        passes, reason = safety.lint_draft(
            draft, source_author=author, recent_openers=recent_openers,
        )
        if not passes:
            log.info("draft_rejected", reason=reason, tweet_id=item.item_id)
            rejected += 1
            continue

        score = voice.score_draft(draft)
        if score < threshold:
            log.info("draft_below_threshold", score=score, threshold=threshold)
            rejected += 1
            continue

        draft_id = state.insert_draft(
            source_id=item.item_id,
            source_url=item.url or "",
            source_author=author,
            source_text=source_text,
            source_followers=followers,
            source_age_min=age_min,
            draft=draft,
            score=score,
        )
        # Mirror to Notion (log only, never approval)
        page_id = notion_mirror.push_draft(state.get_draft(draft_id) or {})
        if page_id:
            state.set_draft_status(draft_id, "pending", notion_page_id=page_id)
        state.record_opener(safety.extract_opener(draft))
        recent_openers = state.recent_openers(limit=5)
        drafted += 1

    print(f"fetch: drafted={drafted}, skipped={skipped}, rejected={rejected}, candidates={len(candidates)}")
    db_id = config.env("NOTION_DB_ID")
    if db_id:
        print(f"Notion DB: https://www.notion.so/{db_id.replace('-', '')} (log only — approve in chat)")
    return 0


# --- review ---

def cmd_review() -> int:
    pending = state.list_drafts(status="pending")
    if not pending:
        print("review: no pending drafts. Run /x-engage fetch first.")
        return 0
    print(f"review: {len(pending)} pending draft(s)\n")
    for i, row in enumerate(pending, start=1):
        src = (row["source_text"] or "").strip().replace("\n", " ")[:140]
        print(f"#{row['id']}  @{row['source_author']} ({row['source_followers']:,} followers) "
              f"· {row['source_age_min']}min ago · score {row['score']:.2f}")
        print(f"  Source: \"{src}\"")
        print(f"  Draft:  \"{row['draft']}\"\n")
    print("Reply with: approve <ids|all>, redraft <id>: <feedback>, kill <id>, good <id>, or publish")
    # Surface the Notion log link so the user can cross-reference in their DB
    db_id = config.env("NOTION_DB_ID") or ""
    if db_id and (config.settings().get("notion") or {}).get("mirror_enabled", True):
        print(f"\nNotion DB: https://www.notion.so/{db_id.replace('-', '')}")
    return 0


# --- approve ---

def cmd_approve(args: list[str]) -> int:
    if not args:
        print("approve: pass ids (e.g. `approve 1a2b 3c4d`) or `approve all`")
        return 1
    if args == ["all"]:
        targets = [r["id"] for r in state.list_drafts(status="pending")]
    else:
        raw = " ".join(args).replace(",", " ").split()
        targets = [t.strip("#") for t in raw if t.strip("#")]
    if not targets:
        print("approve: nothing to approve")
        return 0
    n = 0
    for tid in targets:
        if state.set_draft_status(tid, "approved", approved_at=state.now()):
            row = state.get_draft(tid)
            if row and row.get("notion_page_id"):
                notion_mirror.update_status(row["notion_page_id"], "approved")
            n += 1
    print(f"approve: marked {n} draft(s) approved. Run `/x-engage publish` to ship.")
    return 0


# --- redraft ---

def cmd_redraft(args: list[str]) -> int:
    if len(args) < 2:
        print('redraft: usage `/x-engage redraft <id> "<feedback>"`')
        return 1
    tid = args[0].strip("#")
    feedback = " ".join(args[1:])
    row = state.get_draft(tid)
    if not row:
        print(f"redraft: no draft with id {tid}")
        return 1
    settings = _settings_or_panic()
    max_retry = int((settings.get("drafter") or {}).get("max_redraft_attempts", 2))
    if row["redraft_count"] >= max_retry:
        print(f"redraft: #{tid} hit max redraft attempts ({max_retry})")
        return 1

    new_draft = voice.draft_reply(
        source_text=row["source_text"],
        author=row["source_author"],
        followers=row["source_followers"],
        age_min=row["source_age_min"],
        feedback=feedback,
    )
    recent_openers = state.recent_openers(limit=5)
    passes, reason = safety.lint_draft(
        new_draft, source_author=row["source_author"], recent_openers=recent_openers,
    )
    if not passes:
        print(f"redraft: rejected ({reason}). Try different feedback or `kill {tid}`.")
        return 1
    score = voice.score_draft(new_draft)
    state.set_draft_status(
        tid, "pending",
        draft=new_draft, score=score,
        feedback=feedback, redraft_count=row["redraft_count"] + 1,
    )
    print(f"redraft #{tid}: score {score:.2f}")
    print(f'  Draft: "{new_draft}"')
    return 0


# --- kill ---

def cmd_kill(args: list[str]) -> int:
    if not args:
        print("kill: pass an id")
        return 1
    tid = args[0].strip("#")
    ok = state.set_draft_status(tid, "rejected")
    if ok:
        row = state.get_draft(tid)
        if row and row.get("notion_page_id"):
            notion_mirror.update_status(row["notion_page_id"], "rejected", reason="killed in chat")
        print(f"kill: rejected #{tid}")
    else:
        print(f"kill: no draft with id {tid}")
    return 0 if ok else 1


# --- good (promote a draft to good-drafts.md as a vibe reference) ---

GOOD_DRAFTS_FILE = Path(__file__).resolve().parents[1] / "good-drafts.md"
GOOD_DRAFTS_MAX = 25  # FIFO ceiling — drop oldest entry when this is exceeded


def cmd_good(args: list[str]) -> int:
    """Append a draft to good-drafts.md as a vibe reference for future drafting.

    Usage: /x-engage good <draft_id>

    The drafter will read good-drafts.md at draft time and inject a random 3 of N
    examples as VIBE references (not templates to copy). The safety lint rejects
    new drafts with >30% 4-gram overlap with any example, so the file grows your
    voice signal without causing copy-paste outputs.
    """
    import datetime as _dt
    if not args:
        print("good: pass a draft id (e.g. `good 1a2b`)")
        return 1
    tid = args[0].strip("#")
    row = state.get_draft(tid)
    if not row:
        print(f"good: no draft with id {tid}")
        return 1
    draft_text = (row.get("draft") or "").strip()
    if not draft_text:
        print(f"good: draft #{tid} has no body")
        return 1
    author = row.get("source_author") or "unknown"
    today = _dt.date.today().isoformat()

    GOOD_DRAFTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = GOOD_DRAFTS_FILE.read_text() if GOOD_DRAFTS_FILE.exists() else (
        "# Good drafts — vibe reference (NOT structural templates)\n"
        "# See good-drafts.example.md for format. The CLI appends entries here.\n\n"
    )
    new_entry = f"## {today} · T? · re @{author}\n{draft_text}\n\n"
    combined = existing.rstrip() + "\n\n" + new_entry

    # FIFO trim: keep only the last GOOD_DRAFTS_MAX `## ` entries
    import re as _re
    parts = _re.split(r"(?m)^(## .+)$", combined)
    # parts = [preamble, header1, body1, header2, body2, ...]
    if len(parts) > 1:
        preamble = parts[0]
        headers_bodies = list(zip(parts[1::2], parts[2::2]))
        if len(headers_bodies) > GOOD_DRAFTS_MAX:
            dropped = len(headers_bodies) - GOOD_DRAFTS_MAX
            headers_bodies = headers_bodies[-GOOD_DRAFTS_MAX:]
            print(f"good: trimmed {dropped} oldest entry/entries (cap: {GOOD_DRAFTS_MAX})")
        combined = preamble + "".join(h + b for h, b in headers_bodies)

    GOOD_DRAFTS_FILE.write_text(combined.rstrip() + "\n")
    print(f"good: added #{tid} to {GOOD_DRAFTS_FILE.name} (now {len(_re.findall(r'(?m)^## ', combined))} entries)")
    return 0


# --- publish ---

def cmd_publish() -> int:
    _check_halted()
    settings = _settings_or_panic()
    approved = state.list_approved_for_publish()
    if not approved:
        print("publish: nothing approved. Use `/x-engage review` then `approve <ids|all>`.")
        return 0

    cap_remaining = settings["daily_cap"] - state.count_published_today()
    if cap_remaining <= 0:
        print(f"publish: daily cap hit ({settings['daily_cap']}). Try again tomorrow.")
        return 0

    # Refuse to publish if `require_explicit_approval` is somehow false (defense in depth)
    if not settings.get("require_explicit_approval", True):
        print("publish: REFUSING — require_explicit_approval must be true. Edit config/settings.yml.")
        return 2

    # Lazy import: keep Playwright optional for environments without it
    try:
        from scripts.lib.publisher import publish_batch
    except ImportError as e:
        print(f"publish: Playwright not available — install with `pip install playwright && playwright install chromium`. ({e})")
        return 1

    to_publish = approved[:cap_remaining]
    deferred = len(approved) - len(to_publish)
    result = publish_batch(to_publish, settings)
    print(f"publish: published={result['published']}, failed={result['failed']}, deferred={deferred}")
    if result.get("safety_signal"):
        print(f"ACCOUNT_PAUSED: {result['safety_signal']}")
        return 2
    return 0


# --- status ---

def cmd_status() -> int:
    settings = _settings_or_panic()
    counts = state.queue_counts()
    published_today = state.count_published_today()
    paused = (Path.home() / ".x-engage" / "PAUSED").exists()
    halt = config.env("X_ENGAGE_HALT", "0") == "1"
    print(f"status: published_today={published_today}/{settings['daily_cap']}, "
          f"queue={counts}, paused={paused}, halt_env={halt}")
    return 0


# --- setup ---

def cmd_setup() -> int:
    """Lightweight setup check: bird auth, Notion creds, claude CLI, profile dir."""
    from scripts.lib import bird_health
    ok = True
    # Verify Node is available for the vendored bird-search subprocess
    import shutil
    if shutil.which("node"):
        print("[ok] node on PATH (required for bird-search)")
    else:
        print("[fail] node not found. Install Node.js 22+ (the bird-search reader runs on Node).")
        ok = False
    # Cookies present?
    if config.env("AUTH_TOKEN") and config.env("CT0"):
        print("[ok] X session cookies (AUTH_TOKEN + CT0) present in .env")
    else:
        print("[fail] X session cookies missing. Grab auth_token + ct0 from x.com DevTools "
              "(Application → Cookies → x.com) and add to .env as AUTH_TOKEN + CT0.")
        ok = False
    # Live auth check via bird
    if shutil.which("node"):
        health = bird_health.check_auth()
        if health.authenticated:
            print(f"[ok] bird authenticated via X (source: {health.source})")
        else:
            reason = health.error or "; ".join(health.warnings or []) or "unknown"
            print(f"[fail] bird NOT authenticated: {reason}")
            print("       Cookies may be expired. Log out + back in on x.com, re-grab "
                  "auth_token + ct0, update .env.")
            ok = False
    if config.env("NOTION_TOKEN") and config.env("NOTION_DB_ID"):
        print("[ok] Notion env vars present")
    else:
        print("[fail] NOTION_TOKEN and NOTION_DB_ID required in .env")
        ok = False
    import shutil
    if shutil.which(config.env("CLAUDE_CLI", "claude")):
        print("[ok] claude CLI on PATH")
    else:
        print("[fail] claude CLI not found. Set CLAUDE_CLI in .env or install Claude Code.")
        ok = False
    profile_dir = config.env("X_PROFILE_DIR", "~/.x-engage/chrome-profile")
    print(f"[info] Playwright profile dir: {profile_dir} (you'll log into X here once)")
    return 0 if ok else 1


# --- Main ---

def main() -> int:
    args = sys.argv[1:]
    if not args:
        return cmd_fetch()
    cmd, rest = args[0], args[1:]
    table = {
        "fetch": lambda: cmd_fetch(),
        "review": lambda: cmd_review(),
        "approve": lambda: cmd_approve(rest),
        "redraft": lambda: cmd_redraft(rest),
        "kill": lambda: cmd_kill(rest),
        "good": lambda: cmd_good(rest),
        "publish": lambda: cmd_publish(),
        "status": lambda: cmd_status(),
        "setup": lambda: cmd_setup(),
    }
    if cmd not in table:
        print(f"Unknown command: {cmd}")
        print("Usage: x_engage [fetch|review|approve|redraft|kill|good|publish|status|setup]")
        return 1
    return table[cmd]()


if __name__ == "__main__":
    sys.exit(main())

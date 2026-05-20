"""x-engage CLI orchestrator. Subcommands: fetch | review | approve | redraft | kill | publish | status | setup.

All subcommands print structured one-line summaries the skill wrapper (SKILL.md)
will surface to Dan in chat. Exit code 2 = account safety signal — caller must HALT.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `from scripts.lib...` work when invoked as `python -m scripts.x_engage`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import candidate_pool, config, log, state, voice, safety, notion_mirror
from scripts.lib.fetch import fetch_candidates, CookiesExpired


def _pool_rows_to_items(rows: list[dict]) -> list:
    """Convert candidate_pool rows into SourceItem-shaped objects so the rest
    of cmd_fetch (drafter, lint, scorer) works unchanged. Computes age_min
    fresh from posted_at so stale rows are filtered downstream.
    """
    from datetime import datetime, timezone
    from scripts.lib.vendor.l30d.schema import SourceItem
    now = datetime.now(timezone.utc)
    items: list = []
    for r in rows:
        posted_at_dt = datetime.fromtimestamp(r["posted_at"], tz=timezone.utc)
        age_min = int((now - posted_at_dt).total_seconds() / 60)
        item = SourceItem(
            item_id=r["item_id"],
            source="x",
            title="",
            body=r["source_text"],
            url=r["source_url"],
            author=r["author"],
            published_at=posted_at_dt.isoformat(),
            engagement={"followers": int(r["source_followers"] or 0)},
            metadata={
                "age_min": age_min,
                "subquery_label": r["subquery_label"] or "",
                "from_pool": True,
            },
        )
        item.local_rank_score = float(r["relevance_score"] or 0.0)
        items.append(item)
    return items


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

def cmd_fetch(args: list[str] | None = None) -> int:
    """Draft replies for candidates in the pool (or live-fetched).

    Optional count arg: `/x-engage fetch 30` drafts up to 30 in this run.
    Default: 15. No daily cap enforcement — fetch builds the queue at
    whatever depth you ask for; publish is where account-safety lives.
    """
    _check_halted()
    settings = _settings_or_panic()
    threshold = settings["voice_match_threshold"]

    # Optional count arg — how many drafts to produce in this run.
    # No daily cap; user-controlled per invocation.
    requested = 15
    if args:
        try:
            requested = max(1, min(50, int(args[0])))
        except (ValueError, TypeError):
            pass
    capacity = requested

    log.info("fetch_start", requested=requested)

    # PATH 1: try the candidate pool first. If the background daemon
    # (`run-bg`) is running, the pool has fresh items ready and we skip
    # bird entirely. Drafting becomes 2-3 min instead of 5+.
    max_age = config.safe_int(settings.get("max_age_minutes", 90), 90, 5, 1440)
    pool_rows = candidate_pool.list_fresh(limit=capacity * 3, max_age_min=max_age)
    if pool_rows:
        candidates = _pool_rows_to_items(pool_rows)
        log.info("fetch_source", source="pool", count=len(candidates))
    else:
        # PATH 2 (fallback): no fresh pool → run live discovery, current behavior.
        log.info("fetch_source", source="live")
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
    drafted_pool_ids: list[str] = []
    recent_openers = state.recent_openers(limit=5)
    # Recent published/approved draft texts → drafter uses them to compute the
    # shape-starvation quota (questions/statements/personal-experience mix).
    # Updated in-loop so back-to-back drafts in the same fetch see each other's
    # shape and rotate, not just the pre-fetch baseline.
    recent_drafts = state.recent_published_drafts(limit=voice.SHAPE_HISTORY_WINDOW)

    for item in candidates:
        if drafted >= capacity:
            break
        state.mark_seen(item.item_id)
        if (item.metadata or {}).get("from_pool"):
            drafted_pool_ids.append(item.item_id)
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
            recent_drafts=recent_drafts,
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
                recent_drafts=recent_drafts,
                feedback=retry_hint,
            )
            if draft.strip().upper() == "SKIP" or not draft.strip():
                log.info("draft_skip_after_retry", tweet_id=item.item_id, author=author)
                skipped += 1
                continue
            log.info("draft_recovered_after_retry", tweet_id=item.item_id)

        passes, reason = safety.lint_draft(
            draft, source_author=author, recent_openers=recent_openers,
            recent_drafts=recent_drafts,
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
        # Prepend the fresh draft so the NEXT iteration's starvation quota
        # sees it. Keeps a rolling window of 5 across the whole fetch batch.
        recent_drafts = ([draft] + recent_drafts)[:5]
        drafted += 1

    # Mark pool-sourced items as drafted so they're not re-picked next run.
    # Done in one batch at the end so a mid-run crash leaves the rows
    # selectable next time rather than orphaning them.
    if drafted_pool_ids:
        candidate_pool.mark_drafted(drafted_pool_ids)

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
        recent_drafts=state.recent_published_drafts(limit=voice.SHAPE_HISTORY_WINDOW),
        feedback=feedback,
    )
    recent_openers = state.recent_openers(limit=5)
    passes, reason = safety.lint_draft(
        new_draft, source_author=row["source_author"], recent_openers=recent_openers,
        recent_drafts=state.recent_published_drafts(limit=voice.SHAPE_HISTORY_WINDOW),
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
    # Sync the new text back to Notion so the DB row matches SQLite.
    if row.get("notion_page_id"):
        notion_mirror.update_draft_text(row["notion_page_id"], new_draft)
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

    # No daily cap enforcement — user has explicitly opted out
    # ("everything on my responsibility"). The 90-120s publish gap +
    # per-handle 24h cooldown + 4/30d lifetime cap stay as the safety
    # belt; volume is the user's call.

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

    to_publish = approved  # ship all approved; no cap
    result = publish_batch(to_publish, settings)
    print(f"publish: published={result['published']}, failed={result['failed']}, total_approved={len(approved)}")
    if result.get("safety_signal"):
        print(f"ACCOUNT_PAUSED: {result['safety_signal']}")
        return 2
    return 0


# --- daemon subcommands ---

PLIST_LABEL = "com.x-engage.scan-bg"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def cmd_scan_bg() -> int:
    """One-shot background scan: bird/discovery → filter → write to candidate_pool.
    Called by launchd every 10 min. Never drafts — drafting only happens when
    Dan runs `/x-engage fetch` in chat.
    """
    _check_halted()
    try:
        candidates = fetch_candidates()
    except CookiesExpired as e:
        log.warn("scan_bg_cookies_expired", err=str(e))
        return 2
    except Exception as e:
        log.warn("scan_bg_failed", err=str(e))
        return 1

    written = 0
    for item in candidates:
        author = (item.author or "").lstrip("@").strip()
        if not author:
            continue
        try:
            from datetime import datetime, timezone
            pub_dt = datetime.fromisoformat((item.published_at or "").replace("Z", "+00:00"))
            posted_at = int(pub_dt.timestamp())
        except (ValueError, TypeError, AttributeError):
            continue
        followers = _followers(item)
        candidate_pool.upsert(
            item_id=item.item_id,
            author=author,
            source_text=item.body or item.title or "",
            source_url=item.url or "",
            source_followers=followers,
            posted_at=posted_at,
            subquery_label=str((item.metadata or {}).get("subquery_label") or ""),
            relevance_score=float(item.local_rank_score or 0.0),
        )
        written += 1

    evicted = candidate_pool.evict_stale()
    stats = candidate_pool.pool_stats()
    log.info("scan_bg_done", written=written, evicted=evicted, pool=stats)
    print(f"scan-bg: wrote={written}, evicted={evicted}, "
          f"pool={stats['available']}/{stats['total']} available")
    return 0


def cmd_run_bg() -> int:
    """Install + load the launchd plist so scan-bg runs every 10 min."""
    import shutil
    import os
    project_root = Path(__file__).resolve().parents[1]
    python = shutil.which("python3") or "/usr/bin/python3"
    node = shutil.which("node") or ""
    # launchd doesn't inherit shell PATH, so node/python locations must be
    # explicit. Build a PATH that includes the dirs holding our interpreters
    # + standard system bin dirs the bird-search subprocess might call.
    path_parts: list[str] = []
    if node:
        path_parts.append(str(Path(node).parent))
    if python:
        path_parts.append(str(Path(python).parent))
    path_parts.extend(["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"])
    # Dedup preserving order
    seen: set[str] = set()
    deduped = [p for p in path_parts if not (p in seen or seen.add(p))]
    daemon_path = ":".join(deduped)

    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>scripts.x_engage</string>
    <string>scan-bg</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{project_root}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{daemon_path}</string>
    <key>HOME</key>
    <string>{os.path.expanduser('~')}</string>
  </dict>
  <key>StartInterval</key>
  <integer>600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{project_root}/logs/scan-bg.out</string>
  <key>StandardErrorPath</key>
  <string>{project_root}/logs/scan-bg.err</string>
</dict>
</plist>
"""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist_xml)
    (project_root / "logs").mkdir(exist_ok=True)

    import subprocess
    # Unload first in case it's already running with a stale config
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
    r = subprocess.run(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"run-bg: launchctl load failed — {r.stderr.strip()}")
        return 1
    print(f"run-bg: daemon loaded (runs every 10 min). Plist at {PLIST_PATH}")
    print(f"  Logs: {project_root}/logs/scan-bg.{{out,err}}")
    print(f"  Stop with: /x-engage stop-bg")
    return 0


def cmd_stop_bg() -> int:
    """Unload the launchd plist. Daemon stops; existing pool stays."""
    import subprocess
    if not PLIST_PATH.exists():
        print("stop-bg: daemon not installed (no plist found)")
        return 0
    r = subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True, text=True)
    print(f"stop-bg: daemon unloaded (plist remains at {PLIST_PATH}; rm to fully remove)")
    return 0


def cmd_bg_status() -> int:
    """Show daemon state + candidate pool snapshot."""
    import subprocess
    installed = PLIST_PATH.exists()
    running = False
    if installed:
        r = subprocess.run(["launchctl", "list", PLIST_LABEL], capture_output=True, text=True)
        running = r.returncode == 0
    stats = candidate_pool.pool_stats()
    age = stats["last_fetched_min_ago"]
    age_str = f"{age} min ago" if age >= 0 else "never"
    state_str = "RUNNING" if running else ("INSTALLED but stopped" if installed else "NOT INSTALLED")
    print(f"bg-status: daemon={state_str}")
    print(f"  Pool: {stats['available']} available / {stats['total']} total")
    print(f"  Last fetch: {age_str}")
    return 0


# --- autopilot ---
#
# Autonomous mode: scan pool → draft ONE → lint+score → auto-approve → publish.
# One launchd plist (com.x-engage.autopilot) fires `autopilot-tick` every
# tick_interval_sec. Self-stops on: daily_target hit, stop_at time reached,
# PAUSED flag set, X safety signal. Scan-bg daemon must run in parallel to
# keep the pool fresh.

AUTOPILOT_LABEL = "com.x-engage.autopilot"
AUTOPILOT_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{AUTOPILOT_LABEL}.plist"
AUTOPILOT_CONFIG = Path.home() / ".x-engage" / "autopilot.json"


def _tz_offset_seconds(tz_name: str) -> int:
    """UTC offset (seconds) for the given IANA tz at *now*. DST-aware."""
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        off = datetime.now(ZoneInfo(tz_name)).utcoffset()
        return int(off.total_seconds()) if off else 0
    except Exception:
        return 0


def _autopilot_now_local(tz_name: str):
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


def _parse_hhmm(s: str) -> tuple[int, int]:
    parts = s.strip().split(":")
    return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0


def _load_autopilot_runtime() -> dict:
    import json
    if not AUTOPILOT_CONFIG.exists():
        return {}
    try:
        return json.loads(AUTOPILOT_CONFIG.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_autopilot_runtime(cfg: dict) -> None:
    import json
    AUTOPILOT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    AUTOPILOT_CONFIG.write_text(json.dumps(cfg, indent=2))


def cmd_autopilot(args: list[str]) -> int:
    """Dispatcher for `autopilot {start|stop}` (plus hidden `autopilot-tick`).
    `autopilot status` is folded into the unified `status` command.
    """
    if not args:
        print("autopilot: usage `/x-engage autopilot {start|stop} [target=N] [until=HH:MM]`")
        print("  (For status, use: /x-engage status — shows queue + scan-bg + autopilot)")
        return 1
    sub, rest = args[0], args[1:]
    if sub == "start":
        return cmd_autopilot_start(rest)
    if sub == "stop":
        return cmd_autopilot_stop()
    if sub == "status":
        # Backward-compat alias — defer to unified status
        return cmd_status()
    print(f"autopilot: unknown subcommand '{sub}'. Use start | stop.")
    return 1


def cmd_autopilot_start(args: list[str]) -> int:
    """Install + load launchd plist for autopilot ticks.

    Args: `target=N` (default 50), `until=HH:MM` (default 18:00).
    """
    settings = _settings_or_panic()
    ap_settings = settings.get("autopilot") or {}
    target_default = int(ap_settings.get("daily_target", 50))
    until_default = str(ap_settings.get("stop_at", "18:00"))
    tick_interval = config.safe_int(
        ap_settings.get("tick_interval_sec", 60), 60,
        lower=config.PANIC["min_gap_sec_floor"], upper=600,
    )

    target = target_default
    until = until_default
    for a in args:
        if a.startswith("target="):
            try:
                target = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("until="):
            until = a.split("=", 1)[1].strip()

    panic_max = config.PANIC["autopilot_daily_cap_max"]
    target = config.safe_int(target, target_default, lower=1, upper=panic_max)
    try:
        _parse_hhmm(until)
    except (ValueError, IndexError):
        print(f"autopilot start: invalid until='{until}', expected HH:MM")
        return 1

    if config.is_halted():
        print("autopilot start: REFUSING — kill switch engaged (~/.x-engage/PAUSED or X_ENGAGE_HALT=1)")
        print("  Resolve the safety signal, delete the PAUSED file, then retry.")
        return 2

    _save_autopilot_runtime({
        "target": target,
        "until": until,
        "started_at": state.now(),
    })

    import shutil, os, subprocess
    project_root = Path(__file__).resolve().parents[1]
    python = shutil.which("python3") or "/usr/bin/python3"
    node = shutil.which("node") or ""
    path_parts: list[str] = []
    if node:
        path_parts.append(str(Path(node).parent))
    if python:
        path_parts.append(str(Path(python).parent))
    path_parts.extend(["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"])
    seen: set[str] = set()
    deduped = [p for p in path_parts if not (p in seen or seen.add(p))]
    daemon_path = ":".join(deduped)

    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{AUTOPILOT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>scripts.x_engage</string>
    <string>autopilot-tick</string>
  </array>
  <key>WorkingDirectory</key>
  <string>{project_root}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{daemon_path}</string>
    <key>HOME</key>
    <string>{os.path.expanduser('~')}</string>
  </dict>
  <key>StartInterval</key>
  <integer>{tick_interval}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{project_root}/logs/autopilot.out</string>
  <key>StandardErrorPath</key>
  <string>{project_root}/logs/autopilot.err</string>
</dict>
</plist>
"""
    AUTOPILOT_PLIST.parent.mkdir(parents=True, exist_ok=True)
    AUTOPILOT_PLIST.write_text(plist_xml)
    (project_root / "logs").mkdir(exist_ok=True)

    subprocess.run(["launchctl", "unload", str(AUTOPILOT_PLIST)], capture_output=True)
    r = subprocess.run(["launchctl", "load", str(AUTOPILOT_PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"autopilot start: launchctl load failed — {r.stderr.strip()}")
        return 1

    # Make sure scan-bg is also running so the pool stays full. Autopilot
    # consumes from the pool; scan-bg fills it. Start it automatically if
    # it's not already loaded — autopilot is useless without a fresh pool.
    scan_bg_running = subprocess.run(
        ["launchctl", "list", PLIST_LABEL], capture_output=True, text=True,
    ).returncode == 0
    if not scan_bg_running:
        print("autopilot start: scan-bg not running — starting it now (pool feeder)")
        rc = cmd_run_bg()
        if rc != 0:
            print("autopilot start: WARN — scan-bg failed to start. Autopilot will idle on empty pool.")
            print("  Investigate with: /x-engage bg-status. Fix, then re-run autopilot start.")
    else:
        print("autopilot start: scan-bg already running ✓")

    print(f"autopilot: STARTED — target={target} replies, stops at {until} local ({settings.get('tz', 'UTC')})")
    print(f"  Tick interval: {tick_interval}s. Logs: {project_root}/logs/autopilot.{{out,err}}")
    print(f"  Stop with: /x-engage autopilot stop")
    return 0


def cmd_autopilot_stop() -> int:
    """Unload the autopilot plist. Pool + drafts stay."""
    import subprocess
    if not AUTOPILOT_PLIST.exists():
        print("autopilot stop: not installed (no plist found)")
        return 0
    subprocess.run(["launchctl", "unload", str(AUTOPILOT_PLIST)], capture_output=True, text=True)
    print(f"autopilot stop: daemon unloaded (plist remains at {AUTOPILOT_PLIST})")
    return 0


def cmd_autopilot_status() -> int:
    """Show daemon state + today's published count + time-to-stop."""
    import subprocess
    settings = _settings_or_panic()
    tz_name = str(settings.get("tz", "UTC"))
    runtime = _load_autopilot_runtime()
    installed = AUTOPILOT_PLIST.exists()
    running = False
    if installed:
        running = subprocess.run(
            ["launchctl", "list", AUTOPILOT_LABEL], capture_output=True, text=True,
        ).returncode == 0
    tz_off = _tz_offset_seconds(tz_name)
    published_today = state.count_published_today(tz_offset_sec=tz_off)
    target = int(runtime.get("target", 0))
    until = runtime.get("until", "—")
    paused = (Path.home() / ".x-engage" / "PAUSED").exists()
    state_str = "RUNNING" if running else ("INSTALLED but stopped" if installed else "NOT INSTALLED")

    print(f"autopilot: daemon={state_str}")
    print(f"  Published today: {published_today} / {target if target else '—'}")
    print(f"  Stops at: {until} ({tz_name})")
    print(f"  Paused flag: {paused}")
    if running and target and published_today >= target:
        print("  (Target hit — autopilot will self-stop on next tick.)")
    return 0


def cmd_autopilot_tick() -> int:
    """Single iteration of the autopilot loop. Called by launchd.

    Idempotent: safe to crash and resume. Exit 2 on safety signal — caller HALT.
    """
    import time as _time
    # 1. Halt checks
    if config.is_halted():
        # Silent no-op; auto-stop the daemon so it doesn't keep firing.
        log.info("autopilot_tick_halted_paused")
        cmd_autopilot_stop()
        return 0

    settings = _settings_or_panic()
    ap_settings = settings.get("autopilot") or {}
    runtime = _load_autopilot_runtime()
    tz_name = str(settings.get("tz", "UTC"))
    target = config.safe_int(
        runtime.get("target", ap_settings.get("daily_target", 50)),
        50, lower=1, upper=config.PANIC["autopilot_daily_cap_max"],
    )
    until = str(runtime.get("until", ap_settings.get("stop_at", "18:00")))
    max_age = config.safe_int(ap_settings.get("candidate_max_age_min", 30), 30, 5, 240)
    min_gap = config.safe_int(
        ap_settings.get("min_gap_between_publishes_sec", 90), 90,
        lower=config.PANIC["min_gap_sec_floor"], upper=3600,
    )

    # Time-of-day stop
    try:
        hh, mm = _parse_hhmm(until)
        now_local = _autopilot_now_local(tz_name)
        if (now_local.hour, now_local.minute) >= (hh, mm):
            log.info("autopilot_tick_time_stop", until=until)
            print(f"autopilot-tick: reached stop time {until} — unloading daemon")
            cmd_autopilot_stop()
            return 0
    except (ValueError, IndexError):
        pass

    # Daily target stop
    tz_off = _tz_offset_seconds(tz_name)
    published_today = state.count_published_today(tz_offset_sec=tz_off)
    if published_today >= target:
        log.info("autopilot_tick_target_hit", published=published_today, target=target)
        print(f"autopilot-tick: target {target} hit ({published_today} today) — unloading daemon")
        cmd_autopilot_stop()
        return 0

    # 2. Min-gap check
    last_ts = state.last_published_ts()
    if last_ts and (_time.time() - last_ts) < min_gap:
        wait = int(min_gap - (_time.time() - last_ts))
        log.info("autopilot_tick_min_gap_wait", seconds_left=wait)
        return 0

    # 3. Pull one fresh candidate (over-fetch a few in case top one fails filters)
    pool_rows = candidate_pool.list_fresh(limit=5, max_age_min=max_age)
    if not pool_rows:
        log.info("autopilot_tick_pool_empty", max_age_min=max_age)
        return 0

    threshold = float(settings.get("voice_match_threshold", 0.45))
    recent_openers_list = state.recent_openers(limit=5)
    recent_drafts = state.recent_published_drafts(limit=voice.SHAPE_HISTORY_WINDOW)

    # 4. Draft + lint + score loop — try candidates until one passes
    for item in _pool_rows_to_items(pool_rows):
        candidate_pool.mark_drafted([item.item_id])
        state.mark_seen(item.item_id)
        author = _author(item)
        followers = _followers(item)
        age_min = int(item.metadata.get("age_min") or 0)
        source_text = item.body or item.title or ""

        if state.lifetime_replies_to(author.lower(), within_days=30) >= 4:
            log.info("autopilot_skip_lifetime_cap", author=author)
            continue

        draft = voice.draft_reply(
            source_text=source_text,
            author=author,
            followers=followers,
            age_min=age_min,
            recent_drafts=recent_drafts,
        )
        if draft.strip().upper() == "SKIP" or not draft.strip():
            log.info("autopilot_skip_drafter", tweet_id=item.item_id, author=author)
            continue

        passes, reason = safety.lint_draft(
            draft, source_author=author, recent_openers=recent_openers_list,
            recent_drafts=recent_drafts,
        )
        if not passes:
            log.info("autopilot_draft_rejected", reason=reason, tweet_id=item.item_id)
            continue

        score = voice.score_draft(draft)
        if score < threshold:
            log.info("autopilot_draft_below_threshold", score=score, threshold=threshold)
            continue

        # 5. Insert as approved and publish via existing batch path (single-row)
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
        page_id = notion_mirror.push_draft(state.get_draft(draft_id) or {})
        state.set_draft_status(
            draft_id, "approved",
            approved_at=state.now(),
            notion_page_id=page_id,
        )
        if page_id:
            notion_mirror.update_status(page_id, "approved")
        state.record_opener(safety.extract_opener(draft))

        # publish_batch enforces its own entry safety scan + writes PAUSED on signal.
        # Single-row batch: no intra-batch gap triggers (i>0 path skipped).
        try:
            from scripts.lib.publisher import publish_batch
        except ImportError as e:
            log.warn("autopilot_playwright_missing", err=str(e))
            return 1

        row = state.get_draft(draft_id)
        if not row:
            return 1
        result = publish_batch([row], settings)
        if result.get("safety_signal"):
            log.warn("autopilot_halted_safety", signal=result["safety_signal"])
            print(f"autopilot-tick: ACCOUNT_PAUSED — {result['safety_signal']}")
            cmd_autopilot_stop()
            return 2
        if result["published"] >= 1:
            log.info("autopilot_tick_published", draft_id=draft_id, score=score, author=author)
            print(f"autopilot-tick: published draft={draft_id} score={score:.2f} @{author}")
            return 0
        # publish failed (non-safety) — log and try next candidate next tick
        log.warn("autopilot_publish_failed", draft_id=draft_id)
        return 0

    log.info("autopilot_tick_no_candidate_passed")
    return 0


# --- status (unified: queue + scan-bg + autopilot + safety flags) ---

def cmd_status() -> int:
    """One-shot snapshot of everything. Replaces the old separate
    `status` + `bg-status` + `autopilot status` commands.
    """
    import subprocess
    settings = _settings_or_panic()
    tz_name = str(settings.get("tz", "UTC"))
    counts = state.queue_counts()
    tz_off = _tz_offset_seconds(tz_name)
    published_today = state.count_published_today(tz_offset_sec=tz_off)
    paused = (Path.home() / ".x-engage" / "PAUSED").exists()
    halt_env = config.env("X_ENGAGE_HALT", "0") == "1"

    # scan-bg state
    scanbg_installed = PLIST_PATH.exists()
    scanbg_running = scanbg_installed and subprocess.run(
        ["launchctl", "list", PLIST_LABEL], capture_output=True, text=True,
    ).returncode == 0
    pool = candidate_pool.pool_stats()
    pool_age = pool["last_fetched_min_ago"]
    pool_age_str = f"{pool_age}min ago" if pool_age >= 0 else "never"

    # autopilot state
    ap_installed = AUTOPILOT_PLIST.exists()
    ap_running = ap_installed and subprocess.run(
        ["launchctl", "list", AUTOPILOT_LABEL], capture_output=True, text=True,
    ).returncode == 0
    ap_runtime = _load_autopilot_runtime()
    ap_target = ap_runtime.get("target", "—")
    ap_until = ap_runtime.get("until", "—")

    print("─" * 50)
    print(f"  Queue       : {counts or '{}'}")
    print(f"  Published   : {published_today} today")
    print(f"  Paused flag : {'YES' if paused else 'no'}{'  (HALT env set)' if halt_env else ''}")
    print(f"  Scan-bg     : {'RUNNING' if scanbg_running else ('installed/stopped' if scanbg_installed else 'NOT INSTALLED')}")
    print(f"                pool {pool['available']}/{pool['total']} available · last fetch {pool_age_str}")
    print(f"  Autopilot   : {'RUNNING' if ap_running else ('installed/stopped' if ap_installed else 'NOT INSTALLED')}")
    if ap_running or ap_installed:
        print(f"                target={ap_target} · stop_at={ap_until} ({tz_name})")
    print("─" * 50)
    return 0


# --- setup ---

def cmd_setup(args: list[str] | None = None) -> int:
    """Interactive setup wizard. Walks you through every config step,
    asks questions, and writes files for you.

    Run `setup --check` for a non-interactive verification (the old behavior).
    """
    if args and args[0] in ("--check", "-c", "check"):
        return _cmd_setup_check()
    return _cmd_setup_wizard()


def _prompt(question: str, default: str | None = None, secret: bool = False) -> str:
    """Ask the user a question; return stripped answer (or default if empty)."""
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            if secret:
                import getpass
                ans = getpass.getpass(f"{question}{suffix}: ").strip()
            else:
                ans = input(f"{question}{suffix}: ").strip()
        except EOFError:
            ans = ""
        if ans:
            return ans
        if default is not None:
            return default


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        try:
            ans = input(f"{question}{suffix}: ").strip().lower()
        except EOFError:
            ans = ""
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("  (please answer y or n)")


def _write_env_value(key: str, value: str) -> None:
    """Upsert KEY=VALUE in .env at project root."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    found = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n")


def _cmd_setup_wizard() -> int:
    """Interactive walkthrough — installs everything a non-tech user needs."""
    import shutil
    print()
    print("┌─────────────────────────────────────────────────────────┐")
    print("│            x-engage interactive setup wizard            │")
    print("│  Walks you through every step. Press Enter to accept    │")
    print("│  defaults shown in brackets. Ctrl+C to bail anytime.    │")
    print("└─────────────────────────────────────────────────────────┘")
    print()

    # ─── Step 1: prereq tooling ───
    print("Step 1/6 — Checking required tools on your system…")
    missing = []
    for tool, hint in [
        ("node", "Install Node.js 22+ from https://nodejs.org"),
        ("python3", "Python 3.10+ should already be on macOS — try `xcode-select --install`"),
        (config.env("CLAUDE_CLI", "claude"), "Install Claude Code from https://claude.ai/code"),
    ]:
        if shutil.which(tool):
            print(f"  ✓ {tool} found")
        else:
            print(f"  ✗ {tool} NOT found. {hint}")
            missing.append(tool)
    if missing:
        print(f"\nInstall the missing tools above, then re-run `/x-engage setup`.")
        return 1
    print()

    # ─── Step 2: copy example configs if missing ───
    print("Step 2/6 — Setting up config files…")
    root = Path(__file__).resolve().parents[1]
    for src, dst in [
        ("config/accounts.example.yml", "config/accounts.yml"),
        ("config/topics.example.yml", "config/topics.yml"),
        ("config/settings.example.yml", "config/settings.yml"),
        ("voice-profile.example.md", "voice-profile.personal.md"),
        ("good-drafts.example.md", "good-drafts.md"),
    ]:
        s, d = root / src, root / dst
        if d.exists():
            print(f"  ✓ {dst} already exists, keeping it")
        elif s.exists():
            d.write_text(s.read_text())
            print(f"  ✓ Created {dst} from example")
        else:
            print(f"  ⚠ {src} missing in repo — skip")
    print()

    # ─── Step 3: X session cookies ───
    print("Step 3/6 — X (Twitter) session cookies")
    print("  These let x-engage read your X feed (no password, no API key).")
    print("  How to grab them:")
    print("    1. Open x.com in Chrome, logged in")
    print("    2. Cmd+Opt+I to open DevTools")
    print("    3. Application tab → Cookies → https://x.com")
    print("    4. Find `auth_token` (~40 chars) and `ct0` (~160 chars)")
    print("    5. Copy the VALUE column for each")
    print()
    existing_auth = config.env("AUTH_TOKEN")
    existing_ct0 = config.env("CT0")
    if existing_auth and existing_ct0:
        print(f"  ✓ Found existing AUTH_TOKEN ({existing_auth[:8]}…) and CT0 in .env")
        if not _prompt_yes_no("  Replace them with new values?", default=False):
            print("  → Keeping existing cookies")
        else:
            auth = _prompt("  Paste AUTH_TOKEN", secret=True)
            ct0 = _prompt("  Paste CT0", secret=True)
            _write_env_value("AUTH_TOKEN", auth)
            _write_env_value("CT0", ct0)
            print("  ✓ Updated .env")
    else:
        auth = _prompt("  Paste AUTH_TOKEN", secret=True)
        ct0 = _prompt("  Paste CT0", secret=True)
        _write_env_value("AUTH_TOKEN", auth)
        _write_env_value("CT0", ct0)
        print("  ✓ Saved to .env")
    print()

    # ─── Step 4: Notion (optional) ───
    print("Step 4/6 — Notion mirror (optional)")
    print("  If you skip this, drafts only live in local SQLite + chat.")
    print("  Notion gives you a searchable, shareable log.")
    if _prompt_yes_no("  Set up Notion now?", default=False):
        print("  How:")
        print("    1. Visit https://www.notion.so/profile/integrations")
        print("    2. Create a new integration, copy the secret (starts with `ntn_…`)")
        print("    3. Create a Notion DB with these columns: Name (title), status (select),")
        print("       author, draft, post_text, post_url, scanned_at (date), published_at (date)")
        print("    4. Share the DB with your integration (DB top-right → Connections)")
        print("    5. Copy the DB ID from the URL (the 32-char hex string)")
        token = _prompt("  Paste Notion integration token", secret=True)
        db_id = _prompt("  Paste Notion DB ID (32 hex chars)")
        _write_env_value("NOTION_TOKEN", token)
        _write_env_value("NOTION_DB_ID", db_id)
        print("  ✓ Saved to .env")
    else:
        print("  → Skipped (mirror_enabled defaults to true; the code falls back gracefully)")
    print()

    # ─── Step 5: Playwright login ───
    print("Step 5/6 — One-time X login in the publish browser profile")
    print("  Playwright will open Chrome, you log into X manually,")
    print("  then close the window. Login persists for future publishes.")
    if _prompt_yes_no("  Do this now?", default=True):
        import subprocess
        profile = Path.home() / ".x-engage" / "chrome-profile"
        profile.mkdir(parents=True, exist_ok=True)
        print("  → Launching Chrome — log into X, then close the window")
        script = (
            "from playwright.sync_api import sync_playwright; "
            "from pathlib import Path; "
            f"p='{profile}'; "
            "import sys; "
            "exec(compile('''\n"
            "with sync_playwright() as pw:\n"
            "    ctx = pw.chromium.launch_persistent_context(p, headless=False, viewport={'width':1280,'height':800})\n"
            "    page = ctx.new_page()\n"
            "    page.goto('https://x.com/login')\n"
            "    input('Logged in? Press Enter here to close the browser...')\n"
            "    ctx.close()\n"
            "''', '<wizard>', 'exec'))"
        )
        try:
            subprocess.run(["python3", "-c", script], check=False)
            print("  ✓ Playwright login session captured")
        except Exception as e:
            print(f"  ⚠ Playwright launch failed: {e}")
            print("    Run manually later: see README 'Detailed setup' section")
    else:
        print("  → Skipped (publish won't work until you do this — see README)")
    print()

    # ─── Step 6: optional background daemon ───
    print("Step 6/6 — Background daemon (optional but recommended)")
    print("  Scans X every 10 min for candidates so `/x-engage fetch`")
    print("  is instant when you run it. Costs ~3 sec CPU per cycle.")
    if _prompt_yes_no("  Install + start the daemon now?", default=True):
        cmd_run_bg()
    else:
        print("  → Skipped. Enable later with `/x-engage run-bg`")
    print()

    # ─── Final verification ───
    print("Running final verification…")
    print()
    check_ok = _cmd_setup_check()
    print()
    if check_ok == 0:
        print("┌─────────────────────────────────────────────────────────┐")
        print("│  Setup complete! Next steps:                            │")
        print("│                                                          │")
        print("│  1. Edit voice-profile.personal.md to define your voice │")
        print("│  2. Edit config/accounts.yml to add handles you track   │")
        print("│  3. Edit config/topics.yml to add keywords you care     │")
        print("│     about (or keep the defaults to start)               │")
        print("│  4. Run `/x-engage fetch` to draft your first replies   │")
        print("└─────────────────────────────────────────────────────────┘")
    return check_ok


def _cmd_setup_check() -> int:
    """Lightweight setup verification (the old `cmd_setup` behavior)."""
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


# --- Verify (skill health check) ---
#
# Run after any change to voice/lint/corpus. Goal: catch bloat creep early.
# Targets baked in:
#   - voice-profile.personal.md  : <= 100 lines (hard ceiling 120)
#   - drafter prompt total       : <= 250 lines per call
#   - lint rule count            : <= 20
#   - corpus entries             : >= 8 (need diversity for retrieval)
#   - receipts entries           : >= 10 (need coverage for keyword match)
#
# Also surfaces:
#   - stale files on disk (in references/ but not loaded by code)
#   - lint rules that haven't fired in the last 30 days (deletion candidates)
#   - SKILL.md staleness vs voice.py / safety.py mtimes

def cmd_verify() -> int:
    """One-shot skill health check. Print report, exit 0 if healthy, 1 if warnings."""
    import time
    from pathlib import Path
    from scripts.lib import voice as v_mod
    from scripts.lib import safety as s_mod
    root = Path(__file__).resolve().parents[1]

    warnings: list[str] = []

    def fsize(p: Path) -> int:
        return len(p.read_text().splitlines()) if p.exists() else 0

    print("=" * 60)
    print("X-ENGAGE SKILL HEALTH REPORT")
    print(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # --- Voice profile ---
    vp = root / "voice-profile.personal.md"
    vp_lines = fsize(vp)
    status = "✅" if vp_lines <= 100 else ("⚠️ " if vp_lines <= 120 else "❌")
    print(f"{status} voice-profile.personal.md: {vp_lines} lines (target ≤100, hard ceiling 120)")
    if vp_lines > 100:
        warnings.append(f"voice profile is {vp_lines} lines, target ≤100")
    if vp_lines > 120:
        warnings.append(f"voice profile EXCEEDS hard ceiling of 120 lines — refactor required")

    # --- Corpus ---
    corpus = v_mod._load_corpus()
    print(f"{'✅' if len(corpus) >= 8 else '⚠️ '} dan-x-corpus.md: {len(corpus)} entries (target ≥8 for diversity)")
    if len(corpus) < 8:
        warnings.append(f"only {len(corpus)} corpus entries — retrieval may be repetitive")

    # --- Receipts ---
    receipts = v_mod._load_receipts()
    print(f"{'✅' if len(receipts) >= 10 else '⚠️ '} dan-receipts.md: {len(receipts)} entries (target ≥10 for coverage)")
    if len(receipts) < 10:
        warnings.append(f"only {len(receipts)} receipts — keyword coverage thin")

    # --- Drafter prompt estimate per call ---
    # voice profile + 3 corpus avg + 2 receipts avg + source + scaffolding (~50)
    avg_corpus = sum(e["length"] for e in corpus) // max(len(corpus), 1) if corpus else 0
    avg_corpus_lines = avg_corpus // 50  # rough chars/line for prose
    avg_receipts_lines = 1  # one-liner each
    estimated_prompt_lines = vp_lines + (3 * avg_corpus_lines) + (2 * avg_receipts_lines) + 30
    status = "✅" if estimated_prompt_lines <= 250 else "⚠️ "
    print(f"{status} drafter prompt estimate: ~{estimated_prompt_lines} lines per call (target ≤250)")
    if estimated_prompt_lines > 250:
        warnings.append(f"prompt size ~{estimated_prompt_lines} lines exceeds 250 — investigate retrieval bloat")

    # --- Lint rules ---
    # Thresholds tuned to the actual breakdown:
    #   - banned openers: ~20 stable, AI-tell-driven (won't change much)
    #   - promo/meta-disclosure: ~40 stable, includes NodeSparks-framing bans
    #   - aphorism + listicle: ~30 stable AI cliches
    #   - BANNED_ANYWHERE is the growing one (Dan-flagged drafts) — watch this
    lint_rule_count = (
        len(s_mod.BANNED_OPENERS) +
        len(s_mod.PROMO_PHRASES) +
        len(s_mod.BANNED_ANYWHERE) +
        len(s_mod.APHORISM_PATTERNS) +
        len(s_mod.LISTICLE_PATTERNS)
    )
    status = "✅" if lint_rule_count <= 120 else "⚠️ "
    print(f"{status} lint patterns: {lint_rule_count} total (warn at >120)")
    print(f"     ├─ banned openers: {len(s_mod.BANNED_OPENERS)}")
    print(f"     ├─ promo / meta-disclosure: {len(s_mod.PROMO_PHRASES)}")
    ba_status = "⚠️ " if len(s_mod.BANNED_ANYWHERE) > 25 else "  "
    print(f"     ├─ banned anywhere: {len(s_mod.BANNED_ANYWHERE)} {ba_status}(Dan-flagged set, watch growth past 25)")
    print(f"     ├─ aphorism patterns: {len(s_mod.APHORISM_PATTERNS)}")
    print(f"     └─ listicle patterns: {len(s_mod.LISTICLE_PATTERNS)}")
    if lint_rule_count > 120:
        warnings.append(f"lint has {lint_rule_count} patterns total — audit which are firing")
    if len(s_mod.BANNED_ANYWHERE) > 25:
        warnings.append(f"BANNED_ANYWHERE at {len(s_mod.BANNED_ANYWHERE)} (>25) — most Dan-flagged growth happens here, consider corpus-side fix instead")

    # --- Lint fire-count audit (last 30 days from log) ---
    print()
    print("─── Lint fire-count (last 30 days, from logs/scan-bg.* if present) ───")
    log_files = list((root / "logs").glob("*.err")) if (root / "logs").exists() else []
    if log_files:
        from collections import Counter
        import re
        cutoff = time.time() - (30 * 86400)
        reasons: Counter[str] = Counter()
        for lf in log_files:
            try:
                for line in lf.read_text().splitlines():
                    if '"msg": "draft_rejected"' in line:
                        ts_match = re.search(r'"ts":\s*(\d+)', line)
                        if ts_match and int(ts_match.group(1)) < cutoff:
                            continue
                        r_match = re.search(r'"reason":\s*"([^"]+)"', line)
                        if r_match:
                            reasons[r_match.group(1).split(":")[0].strip()] += 1
            except Exception:
                pass
        if reasons:
            for reason, count in reasons.most_common(10):
                print(f"     {count:>5}x  {reason}")
        else:
            print("     (no rejection logs found in window)")
    else:
        print("     (no log files in logs/ — fire-count audit unavailable)")

    # --- Stale file detection ---
    print()
    print("─── Stale file scan (references/ entries not loaded by code) ───")
    refs_dir = root / "references"
    if refs_dir.exists():
        for ref in refs_dir.iterdir():
            if ref.is_dir() and ref.name == "_archive":
                continue
            if not ref.is_file() or ref.suffix != ".md":
                continue
            # Check if referenced anywhere in scripts/
            scripts_dir = root / "scripts"
            grep_target = ref.name
            loaded = False
            try:
                import subprocess
                r = subprocess.run(
                    ["grep", "-r", grep_target, str(scripts_dir)],
                    capture_output=True, text=True, timeout=5,
                )
                loaded = bool(r.stdout.strip())
            except Exception:
                pass
            if loaded:
                print(f"     ✅  {ref.name} — loaded by code")
            else:
                print(f"     ⚠️   {ref.name} — NOT referenced in scripts/ → archive candidate")
                warnings.append(f"references/{ref.name} appears stale (no scripts/ reference)")

    # --- SKILL.md vs code mtime ---
    print()
    skill_md = Path.home() / ".claude" / "skills" / "x-engage" / "SKILL.md"
    voice_py = root / "scripts" / "lib" / "voice.py"
    safety_py = root / "scripts" / "lib" / "safety.py"
    if skill_md.exists() and voice_py.exists():
        skill_age = skill_md.stat().st_mtime
        code_age = max(voice_py.stat().st_mtime, safety_py.stat().st_mtime)
        if code_age > skill_age + 3600:  # code is >1h newer than SKILL.md
            age_diff = (code_age - skill_age) / 3600
            print(f"⚠️   SKILL.md is {age_diff:.1f}h older than voice.py/safety.py → may be stale")
            warnings.append(f"SKILL.md last touched {age_diff:.1f}h before drafter code — review")
        else:
            print(f"✅  SKILL.md and code in sync (within 1h)")

    # --- Summary ---
    print()
    print("=" * 60)
    if warnings:
        print(f"❌  {len(warnings)} warning(s) — review before next update:")
        for w in warnings:
            print(f"     • {w}")
        print("=" * 60)
        return 1
    print("✅  ALL CHECKS PASSED — skill is healthy")
    print("=" * 60)
    return 0


# --- Main ---

def main() -> int:
    args = sys.argv[1:]
    if not args:
        return cmd_fetch()
    cmd, rest = args[0], args[1:]
    table = {
        "fetch": lambda: cmd_fetch(rest),
        "review": lambda: cmd_review(),
        "approve": lambda: cmd_approve(rest),
        "redraft": lambda: cmd_redraft(rest),
        "kill": lambda: cmd_kill(rest),
        "good": lambda: cmd_good(rest),
        "publish": lambda: cmd_publish(),
        "status": lambda: cmd_status(),
        "setup": lambda: cmd_setup(rest),
        "scan-bg": lambda: cmd_scan_bg(),       # internal: launchd-only
        "run-bg": lambda: cmd_run_bg(),
        "stop-bg": lambda: cmd_stop_bg(),
        "bg-status": lambda: cmd_status(),       # alias → unified status
        "verify": lambda: cmd_verify(),
        "autopilot": lambda: cmd_autopilot(rest),
        "autopilot-tick": lambda: cmd_autopilot_tick(),
    }
    if cmd not in table:
        print(f"Unknown command: {cmd}")
        print("Usage: x_engage [fetch|review|approve|redraft|kill|good|publish|"
              "status|setup|run-bg|stop-bg|bg-status|scan-bg|verify|autopilot]")
        return 1
    return table[cmd]()


if __name__ == "__main__":
    sys.exit(main())

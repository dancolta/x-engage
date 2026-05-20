"""SQLite state: draft queue, cooldowns, seen-posts, opener history."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "state" / "x-engage.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_author TEXT NOT NULL,
    source_text TEXT NOT NULL,
    source_followers INTEGER NOT NULL DEFAULT 0,
    source_age_min INTEGER NOT NULL DEFAULT 0,
    draft TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | published | failed
    feedback TEXT,
    redraft_count INTEGER NOT NULL DEFAULT 0,
    notion_page_id TEXT,
    created_at INTEGER NOT NULL,
    approved_at INTEGER,
    published_url TEXT,
    published_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_source ON drafts(source_id);

CREATE TABLE IF NOT EXISTS handles_cooldown (
    handle TEXT PRIMARY KEY,
    last_reply_at INTEGER NOT NULL,
    lifetime_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS seen_posts (
    post_id TEXT PRIMARY KEY,
    seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS opener_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opener TEXT NOT NULL,
    used_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opener_used_at ON opener_history(used_at);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


# --- Drafts ---

def insert_draft(*, source_id: str, source_url: str, source_author: str, source_text: str,
                 source_followers: int, source_age_min: int, draft: str, score: float) -> str:
    draft_id = uuid.uuid4().hex[:8]
    with _conn() as c:
        c.execute(
            """INSERT INTO drafts (id, source_id, source_url, source_author, source_text,
                                   source_followers, source_age_min, draft, score, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (draft_id, source_id, source_url, source_author, source_text,
             source_followers, source_age_min, draft, score, now()),
        )
    return draft_id


def list_drafts(status: str | None = None) -> list[dict[str, Any]]:
    with _conn() as c:
        if status:
            rows = c.execute("SELECT * FROM drafts WHERE status = ? ORDER BY score DESC, created_at ASC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM drafts ORDER BY created_at DESC LIMIT 100").fetchall()
    return [dict(r) for r in rows]


def get_draft(draft_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    return dict(row) if row else None


def set_draft_status(draft_id: str, status: str, **extras: Any) -> bool:
    """Set status and optional fields. Returns True if row existed."""
    allowed = {"feedback", "notion_page_id", "approved_at", "published_url", "published_at",
               "draft", "score", "redraft_count"}
    sets = ["status = ?"]
    vals: list[Any] = [status]
    for k, v in extras.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(draft_id)
    with _conn() as c:
        cur = c.execute(f"UPDATE drafts SET {', '.join(sets)} WHERE id = ?", vals)
        return cur.rowcount > 0


def list_approved_for_publish() -> list[dict[str, Any]]:
    """Drafts ready to publish, ordered oldest-approval-first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM drafts WHERE status = 'approved' ORDER BY approved_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def last_published_ts() -> int | None:
    """Most recent published_at timestamp, or None if nothing ever published."""
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(published_at) AS ts FROM drafts WHERE status='published'"
        ).fetchone()
    return int(row["ts"]) if row and row["ts"] else None


def count_published_today(tz_offset_sec: int = 0) -> int:
    """Count drafts published since midnight in target tz."""
    midnight = _midnight_in_tz(tz_offset_sec)
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM drafts WHERE status='published' AND published_at >= ?",
            (midnight,),
        ).fetchone()
    return int(row["n"]) if row else 0


def _midnight_in_tz(tz_offset_sec: int) -> int:
    t = now() + tz_offset_sec
    midnight_local = t - (t % 86400)
    return midnight_local - tz_offset_sec


# --- Cooldowns ---

def is_on_cooldown(handle: str, hours: int) -> bool:
    cutoff = now() - hours * 3600
    with _conn() as c:
        row = c.execute(
            "SELECT last_reply_at FROM handles_cooldown WHERE handle = ?", (handle,)
        ).fetchone()
    return bool(row and row["last_reply_at"] > cutoff)


def touch_cooldown(handle: str) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO handles_cooldown (handle, last_reply_at, lifetime_count)
               VALUES (?, ?, 1)
               ON CONFLICT(handle) DO UPDATE SET
                 last_reply_at = excluded.last_reply_at,
                 lifetime_count = handles_cooldown.lifetime_count + 1""",
            (handle, now()),
        )


def lifetime_replies_to(handle: str, within_days: int) -> int:
    """Count replies to handle within the last N days (approx via last_reply_at + lifetime_count)."""
    cutoff = now() - within_days * 86400
    with _conn() as c:
        row = c.execute(
            "SELECT lifetime_count FROM handles_cooldown WHERE handle = ? AND last_reply_at >= ?",
            (handle, cutoff),
        ).fetchone()
    return int(row["lifetime_count"]) if row else 0


# --- Seen posts ---

def is_seen(post_id: str) -> bool:
    with _conn() as c:
        row = c.execute("SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)).fetchone()
    return bool(row)


def mark_seen(post_id: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_posts (post_id, seen_at) VALUES (?, ?)",
            (post_id, now()),
        )


# --- Opener history ---

def record_opener(opener: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO opener_history (opener, used_at) VALUES (?, ?)", (opener, now()))


def recent_published_drafts(limit: int = 5) -> list[str]:
    """Return the last N published draft texts, newest first. Used by the
    drafter to inject a 'recent shapes' starvation quota — forces variety
    across questions / statements / personal-experience replies (50/30/20
    target per 2026 builder-account research).

    Falls back to approved drafts if not enough published rows exist
    (covers the first runs after a cookie reset or fresh install)."""
    with _conn() as c:
        rows = c.execute(
            """SELECT draft FROM drafts
               WHERE status IN ('published', 'approved')
               ORDER BY COALESCE(published_at, approved_at, created_at) DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [r["draft"] for r in rows]


def recent_openers(limit: int = 5) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT opener FROM opener_history ORDER BY used_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["opener"] for r in rows]


# --- Counts ---

def recent_oss_anchor_count(window: int, markers: tuple[str, ...]) -> int:
    """Count how many of the most recent `window` published drafts contain any
    OSS-anchor marker (substring, case-insensitive). Used by the safety lint to
    enforce the T4b frequency cap.
    """
    if window <= 0 or not markers:
        return 0
    with _conn() as c:
        rows = c.execute(
            "SELECT draft FROM drafts WHERE status='published' "
            "ORDER BY published_at DESC LIMIT ?",
            (window,),
        ).fetchall()
    hits = 0
    for r in rows:
        low = (r["draft"] or "").lower()
        if any(m in low for m in markers):
            hits += 1
    return hits


def queue_counts() -> dict[str, int]:
    with _conn() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM drafts GROUP BY status"
        ).fetchall()
    return {r["status"]: int(r["n"]) for r in rows}

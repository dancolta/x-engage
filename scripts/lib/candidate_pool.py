"""Candidate pool — SQLite table holding fresh posts a background daemon
has surfaced. The interactive `/x-engage fetch` command pulls from here
instead of firing bird subqueries directly, so user-facing runs become
near-instant and decoupled from X's rate limits.

Schema:
  - item_id (text, primary key)      — X tweet id (real, not "X1"/"X2")
  - author (text)                    — handle without @
  - source_text (text)               — post body (truncated to 500)
  - source_url (text)                — permalink
  - source_followers (integer)       — author follower count at fetch time
  - posted_at (integer)              — unix epoch of original post time
  - fetched_at (integer)             — when daemon wrote this row
  - subquery_label (text)            — which topic/account batch found it
  - relevance_score (real)           — from signals.py local_rank_score
  - drafted (integer)                — 0 = available, 1 = already drafted

Eviction: rows older than MAX_POOL_AGE_SEC are pruned on every write.
That keeps the pool small and ensures we never draft for a post that
has aged out of the X reply window.

Notion is NOT touched here. Pool is internal-only; only drafts (rows
in `drafts` table) ever sync to Notion.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "state" / "x-engage.sqlite"

# Drop rows older than this. Aligns with max_age_minutes (default 90) plus
# a generous grace window so candidates from earlier scans persist long enough
# to actually be drafted across multiple sessions. 4h ceiling = daemon has 24
# scan cycles to refresh any given candidate; the reply-window check at draft
# time (list_fresh max_age_min=90) still prevents drafting on stale posts.
MAX_POOL_AGE_SEC = 8 * 60 * 60  # 8 hours

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate_pool (
    item_id TEXT PRIMARY KEY,
    author TEXT NOT NULL,
    source_text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_followers INTEGER NOT NULL DEFAULT 0,
    posted_at INTEGER NOT NULL,
    fetched_at INTEGER NOT NULL,
    subquery_label TEXT,
    relevance_score REAL NOT NULL DEFAULT 0.0,
    drafted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pool_drafted ON candidate_pool(drafted, relevance_score DESC);
CREATE INDEX IF NOT EXISTS idx_pool_fetched ON candidate_pool(fetched_at);
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


def upsert(*, item_id: str, author: str, source_text: str, source_url: str,
           source_followers: int, posted_at: int, subquery_label: str,
           relevance_score: float) -> bool:
    """Insert a candidate or refresh fetched_at on an existing row.

    Returns True if newly inserted, False if updated.
    """
    now = int(time.time())
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO candidate_pool
               (item_id, author, source_text, source_url, source_followers,
                posted_at, fetched_at, subquery_label, relevance_score, drafted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
               ON CONFLICT(item_id) DO UPDATE SET
                 fetched_at = excluded.fetched_at,
                 source_followers = excluded.source_followers,
                 relevance_score = MAX(candidate_pool.relevance_score, excluded.relevance_score)
            """,
            (item_id, author.lower(), source_text[:500], source_url,
             source_followers, posted_at, now, subquery_label, relevance_score),
        )
        return cur.rowcount > 0 and not cur.lastrowid == 0


def list_fresh(limit: int = 30, max_age_min: int = 90) -> list[dict[str, Any]]:
    """Return up to `limit` undrafted candidates whose post age is still inside
    the reply window. Sorted by NEWEST FIRST (posted_at DESC), then by
    relevance_score DESC as tiebreak — so /x-engage fetch always drafts the
    most recent candidates first, and subsequent fetches naturally move to
    older items as the newer ones get marked drafted=1.
    """
    cutoff_posted_at = int(time.time()) - max_age_min * 60
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM candidate_pool
               WHERE drafted = 0 AND posted_at >= ?
               ORDER BY posted_at DESC, relevance_score DESC
               LIMIT ?""",
            (cutoff_posted_at, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_drafted(item_ids: list[str]) -> int:
    """Flip `drafted` to 1 so the same candidate isn't picked again."""
    if not item_ids:
        return 0
    placeholders = ",".join("?" * len(item_ids))
    with _conn() as c:
        cur = c.execute(
            f"UPDATE candidate_pool SET drafted = 1 WHERE item_id IN ({placeholders})",
            item_ids,
        )
        return cur.rowcount


def evict_stale() -> int:
    """Delete rows older than MAX_POOL_AGE_SEC. Called by the daemon every cycle."""
    cutoff = int(time.time()) - MAX_POOL_AGE_SEC
    with _conn() as c:
        cur = c.execute("DELETE FROM candidate_pool WHERE fetched_at < ?", (cutoff,))
        return cur.rowcount


def pool_stats() -> dict[str, int]:
    """Snapshot of the pool for status output."""
    now = int(time.time())
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM candidate_pool").fetchone()["n"]
        undrafted = c.execute(
            "SELECT COUNT(*) AS n FROM candidate_pool WHERE drafted = 0"
        ).fetchone()["n"]
        last_row = c.execute(
            "SELECT MAX(fetched_at) AS ts FROM candidate_pool"
        ).fetchone()
        last_fetched = (last_row["ts"] or 0) if last_row else 0
    age_min = max(0, (now - last_fetched) // 60) if last_fetched else None
    return {
        "total": int(total),
        "available": int(undrafted),
        "last_fetched_min_ago": age_min if age_min is not None else -1,
    }

"""Notion log mirror. Schema matches the shared LinkedIn+X Comments DB
(collection://3574431f-d8eb-8110-8adc-000bfe6b0af1):

  Name (title)     — short label "@author: source preview"
  author (text)    — source author handle
  draft (text)     — generated reply
  final_text (text)— Dan's optional edits; if set, used instead of draft
  post_text (text) — source post text
  post_url (url)   — source tweet URL
  scanned_at (date)— when this draft was created
  published_at(date)— when shipped
  reason (text)    — why skipped/failed
  status (select)  — pending | approved | publishing | published | failed | skipped | deferred

Notion is a LOG, not the approval surface. Chat is the approval surface.
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

from . import config, log

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Map internal SQLite statuses -> Notion select options
STATUS_MAP = {
    "pending": "pending",
    "approved": "approved",
    "publishing": "publishing",
    "published": "published",
    "failed": "failed",
    "rejected": "skipped",   # we use "rejected" locally; Notion has "skipped"
    "deferred": "deferred",
}


def _enabled() -> bool:
    s = config.settings().get("notion") or {}
    return bool(s.get("mirror_enabled", True)) and bool(config.env("NOTION_TOKEN")) and bool(config.env("NOTION_DB_ID"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.env('NOTION_TOKEN')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    url = f"{NOTION_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.warn("notion_request_failed", method=method, path=path, error=str(e))
        return {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(epoch: int | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()


def push_draft(draft_row: dict[str, Any]) -> str | None:
    """Create a Notion page mirroring a SQLite draft row. Returns Notion page id."""
    if not _enabled():
        return None
    db_id = config.env("NOTION_DB_ID")
    src_preview = (draft_row.get("source_text") or "").strip().replace("\n", " ")[:60]
    title = f"@{draft_row['source_author']}: {src_preview}"
    props = {
        "Name":       {"title": [{"text": {"content": title[:2000]}}]},
        "status":     {"select": {"name": "pending"}},
        "author":     {"rich_text": [{"text": {"content": draft_row["source_author"][:1900]}}]},
        "draft":      {"rich_text": [{"text": {"content": draft_row["draft"][:1900]}}]},
        "post_text":  {"rich_text": [{"text": {"content": (draft_row["source_text"] or "")[:1900]}}]},
        "post_url":   {"url": draft_row.get("source_url") or None},
        "scanned_at": {"date": {"start": _iso(draft_row.get("created_at")) or _iso_now()}},
    }
    resp = _request("POST", "/pages", {
        "parent": {"database_id": db_id},
        "properties": props,
    })
    return resp.get("id")


def update_status(page_id: str, internal_status: str,
                  published_url: str | None = None,
                  reason: str | None = None,
                  final_text: str | None = None) -> None:
    if not _enabled() or not page_id:
        return
    notion_status = STATUS_MAP.get(internal_status, internal_status)
    props: dict[str, Any] = {"status": {"select": {"name": notion_status}}}
    if published_url:
        props["post_url"] = {"url": published_url}  # update parent URL only if changed
        props["published_at"] = {"date": {"start": _iso_now()}}
    if reason:
        props["reason"] = {"rich_text": [{"text": {"content": reason[:1900]}}]}
    if final_text:
        props["final_text"] = {"rich_text": [{"text": {"content": final_text[:1900]}}]}
    _request("PATCH", f"/pages/{page_id}", {"properties": props})


def fetch_final_text(page_id: str) -> str | None:
    """Read final_text override from Notion (if Dan edited the draft in Notion before publish)."""
    if not _enabled() or not page_id:
        return None
    resp = _request("GET", f"/pages/{page_id}")
    props = (resp.get("properties") or {}).get("final_text") or {}
    rt = props.get("rich_text") or []
    if not rt:
        return None
    return "".join(p.get("plain_text", "") for p in rt).strip() or None

"""Structured logging for x-comment."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_LEVEL = _LEVELS.get(os.environ.get("X_COMMENT_LOG", "INFO").upper(), 20)


def _emit(level: str, msg: str, **fields: Any) -> None:
    if _LEVELS[level] < _LEVEL:
        return
    record = {"ts": int(time.time()), "level": level, "msg": msg, **fields}
    sys.stderr.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def debug(msg: str, **fields: Any) -> None: _emit("DEBUG", msg, **fields)
def info(msg: str, **fields: Any) -> None: _emit("INFO", msg, **fields)
def warn(msg: str, **fields: Any) -> None: _emit("WARN", msg, **fields)
def error(msg: str, **fields: Any) -> None: _emit("ERROR", msg, **fields)


def log_event_to_file(event_type: str, data: dict, log_dir: Path) -> None:
    """Append a structured event to logs/<event_type>-<date>.jsonl."""
    log_dir.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d")
    path = log_dir / f"{event_type}-{date}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": int(time.time()), **data}, ensure_ascii=False) + "\n")

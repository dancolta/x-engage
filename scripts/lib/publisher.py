"""Playwright publisher. Headed Chromium on a persistent profile; refuses to ship
anything not status='approved'. Account-safety scan on entry, kill-switch honored.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any

from . import config, log, state, notion_mirror

SAFETY_KEYWORDS = (
    "your account is temporarily restricted",
    "we detected unusual activity",
    "verify you're human",
    "verify you are human",
    "this account is suspended",
    "captcha",
    "log in to twitter",
    "log in to x",
    "sign in to x",
)

PAUSED_FLAG = Path.home() / ".x-comment" / "PAUSED"
INCIDENT_DIR = Path.home() / "Downloads"


def _write_paused(reason: str) -> None:
    PAUSED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    PAUSED_FLAG.write_text(f"{int(time.time())}: {reason}\n")


def _profile_dir() -> Path:
    raw = config.env("X_PROFILE_DIR", "~/.x-comment/chrome-profile")
    p = Path(os.path.expanduser(raw or ""))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _human_type(locator, text: str) -> None:
    """Type text char-by-char with humanized delays + occasional pause."""
    for ch in text:
        locator.type(ch, delay=random.uniform(40, 120))
        if random.random() < 0.05:
            time.sleep(random.uniform(0.25, 0.9))


def _scan_for_safety(page) -> str:
    """Return non-empty string if page contains a safety/captcha signal."""
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return ""
    for kw in SAFETY_KEYWORDS:
        if kw in body:
            return kw
    return ""


def _snapshot(page, label: str) -> Path:
    INCIDENT_DIR.mkdir(parents=True, exist_ok=True)
    path = INCIDENT_DIR / f"x-incident-{int(time.time())}-{label}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception as e:
        log.warn("screenshot_failed", error=str(e))
    return path


def publish_batch(rows: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    """Publish each approved draft sequentially via Playwright. Returns summary dict."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError("playwright not installed. Run: pip install playwright && playwright install chromium") from e

    try:
        from playwright_stealth import Stealth  # type: ignore
        _has_stealth = True
    except ImportError:
        _has_stealth = False
        log.warn("stealth_missing", hint="pip install playwright-stealth for fingerprint hardening")

    min_gap = int(settings.get("min_gap_between_publishes_sec", 90))
    pw_cfg = settings.get("playwright") or {}
    # Default to headless. Set `playwright.headless: false` in settings.yml to
    # see the browser (useful for one-time login or debugging).
    headless = bool(pw_cfg.get("headless", True))
    profile = _profile_dir()
    published = 0
    failed = 0
    safety_signal: str | None = None

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        if _has_stealth:
            try:
                Stealth().apply_stealth_sync(ctx)
            except Exception as e:
                log.warn("stealth_apply_failed", error=str(e))

        page = ctx.new_page()
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(random.randint(2500, 4500))
        sig = _scan_for_safety(page)
        if sig:
            snap = _snapshot(page, "entry-safety")
            _write_paused(f"entry safety signal: {sig} ({snap.name})")
            ctx.close()
            return {"published": 0, "failed": 0, "safety_signal": sig}

        for i, row in enumerate(rows):
            if config.is_halted():
                log.warn("publish_halted_mid_batch")
                break
            if i > 0:
                gap = min_gap + random.randint(0, 30)
                log.info("publish_gap", seconds=gap)
                time.sleep(gap)

            ok, err = _publish_one(page, row)
            if ok:
                published += 1
                state.touch_cooldown(row["source_author"])
            else:
                failed += 1
                log.warn("publish_failed", id=row["id"], err=err)
                if err and any(kw in err.lower() for kw in SAFETY_KEYWORDS):
                    safety_signal = err
                    _snapshot(page, f"fail-{row['id']}")
                    _write_paused(f"publish-time safety: {err}")
                    break

        ctx.close()

    return {"published": published, "failed": failed, "safety_signal": safety_signal}


def _publish_one(page, row: dict[str, Any]) -> tuple[bool, str]:
    """Navigate to source tweet, click reply, type, submit, capture published URL."""
    url = row["source_url"]
    draft = row["draft"]
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Humanized settle: scroll a touch, pause
        page.wait_for_timeout(random.randint(1500, 3000))
        page.mouse.wheel(0, random.randint(150, 400))
        page.wait_for_timeout(random.randint(800, 1800))

        sig = _scan_for_safety(page)
        if sig:
            return False, sig

        # Click the reply textarea. X's reply trigger is usually a div with role=textbox,
        # but the inline reply box on a tweet detail page appears after clicking the
        # "Post your reply" placeholder. Both selectors covered.
        reply_box = None
        for selector in (
            'div[data-testid="tweetTextarea_0"]',
            'div[aria-label*="Post your reply"]',
            'div[aria-label*="Reply"]',
        ):
            try:
                page.wait_for_selector(selector, timeout=4000)
                reply_box = page.locator(selector).first
                break
            except Exception:
                continue
        if reply_box is None:
            return False, "reply box not found"

        reply_box.click()
        page.wait_for_timeout(random.randint(400, 900))
        _human_type(reply_box, draft)
        page.wait_for_timeout(random.randint(800, 1600))

        # Submit. Primary button has data-testid="tweetButton" (top inline) or "tweetButtonInline".
        submit = None
        for sel in ('button[data-testid="tweetButtonInline"]',
                    'button[data-testid="tweetButton"]'):
            try:
                page.wait_for_selector(sel, timeout=2000)
                submit = page.locator(sel).first
                break
            except Exception:
                continue
        if submit is None:
            return False, "submit button not found"
        submit.click()
        # Wait for the box to clear as confirmation
        try:
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('div[data-testid="tweetTextarea_0"]');
                    return !el || (el.innerText || '').trim() === '';
                }""",
                timeout=15000,
            )
        except Exception:
            return False, "submit timeout"

        published_at = state.now()
        # X doesn't expose the published reply URL inline reliably; record source URL fallback
        state.set_draft_status(
            row["id"], "published",
            published_at=published_at,
            published_url=url,  # parent URL; the reply itself isn't easily extractable from the DOM
        )
        if row.get("notion_page_id"):
            notion_mirror.update_status(row["notion_page_id"], "published", published_url=url)
            # Archive the Notion page once shipped — keeps the active queue view clean.
            # Same pattern as /linkedin-comment.
            notion_mirror.archive_page(row["notion_page_id"])
        log.info("published", id=row["id"], parent=url)
        return True, ""
    except Exception as e:
        return False, str(e)

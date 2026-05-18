"""One-off thread publisher. Reuses x-engage's persistent Chrome profile +
stealth so the logged-in session and fingerprint stay consistent with replies.

Usage:
    python publish_thread.py path/to/thread.json [--headed]

thread.json schema:
    {
      "main": "first tweet text",
      "replies": ["second tweet", "third tweet"]
    }

Posts as a connected thread via X's compose+ flow (single submit at the end).
Headless by default.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib import config, log  # noqa: E402

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


def _profile_dir() -> Path:
    raw = config.env("X_PROFILE_DIR", "~/.x-engage/chrome-profile")
    p = Path(os.path.expanduser(raw or ""))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _human_type(locator, text: str) -> None:
    for ch in text:
        locator.type(ch, delay=random.uniform(40, 120))
        if random.random() < 0.05:
            time.sleep(random.uniform(0.25, 0.9))


def _scan_for_safety(page) -> str:
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:
        return ""
    for kw in SAFETY_KEYWORDS:
        if kw in body:
            return kw
    return ""


def _snapshot(page, label: str) -> Path:
    out = Path.home() / "Downloads" / f"x-thread-{int(time.time())}-{label}.png"
    try:
        page.screenshot(path=str(out), full_page=True)
    except Exception as e:
        log.warn("screenshot_failed", error=str(e))
    return out


def publish_thread(main: str, replies: list[str], headless: bool = True) -> dict:
    from playwright.sync_api import sync_playwright

    try:
        from playwright_stealth import Stealth
        has_stealth = True
    except ImportError:
        has_stealth = False

    profile = _profile_dir()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        if has_stealth:
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
            log.warn("entry_safety_signal", signal=sig, snapshot=str(snap))
            ctx.close()
            return {"ok": False, "error": f"safety: {sig}", "snapshot": str(snap)}

        # Open compose via the "n" keyboard shortcut (most stable).
        page.keyboard.press("n")
        page.wait_for_timeout(random.randint(1200, 2200))

        try:
            page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=8000)
        except Exception:
            snap = _snapshot(page, "no-compose")
            ctx.close()
            return {"ok": False, "error": "compose textarea not found", "snapshot": str(snap)}

        box0 = page.locator('div[data-testid="tweetTextarea_0"]').first
        box0.click()
        page.wait_for_timeout(random.randint(400, 900))
        _human_type(box0, main)
        page.wait_for_timeout(random.randint(900, 1800))

        for idx, reply_text in enumerate(replies, start=1):
            add_btn = None
            for sel in (
                'button[data-testid="addButton"]',
                'button[aria-label="Add post"]',
                'button[aria-label*="Add"]',
            ):
                try:
                    page.wait_for_selector(sel, timeout=4000)
                    add_btn = page.locator(sel).first
                    break
                except Exception:
                    continue
            if add_btn is None:
                snap = _snapshot(page, f"no-add-{idx}")
                ctx.close()
                return {"ok": False, "error": f"add button not found before reply {idx}", "snapshot": str(snap)}
            add_btn.click()
            page.wait_for_timeout(random.randint(700, 1300))

            sel_textarea = f'div[data-testid="tweetTextarea_{idx}"]'
            try:
                page.wait_for_selector(sel_textarea, timeout=5000)
            except Exception:
                snap = _snapshot(page, f"no-textarea-{idx}")
                ctx.close()
                return {"ok": False, "error": f"reply textarea {idx} not found", "snapshot": str(snap)}
            box = page.locator(sel_textarea).first
            box.click()
            page.wait_for_timeout(random.randint(400, 900))
            _human_type(box, reply_text)
            page.wait_for_timeout(random.randint(900, 1800))

        page.wait_for_timeout(random.randint(1200, 2200))
        submit = None
        for sel in (
            'button[data-testid="tweetButton"]',
            'button[data-testid="tweetButtonInline"]',
        ):
            try:
                page.wait_for_selector(sel, timeout=4000)
                submit = page.locator(sel).first
                break
            except Exception:
                continue
        if submit is None:
            snap = _snapshot(page, "no-submit")
            ctx.close()
            return {"ok": False, "error": "submit button not found", "snapshot": str(snap)}

        submit.click()
        try:
            page.wait_for_function(
                """() => !document.querySelector('div[data-testid="tweetTextarea_0"]')""",
                timeout=20000,
            )
        except Exception:
            snap = _snapshot(page, "submit-timeout")
            ctx.close()
            return {"ok": False, "error": "submit timeout (modal did not close)", "snapshot": str(snap)}

        page.wait_for_timeout(2000)
        ctx.close()
        return {"ok": True, "main": main, "reply_count": len(replies)}


def main():
    if len(sys.argv) < 2:
        print("usage: publish_thread.py path/to/thread.json [--headed]", file=sys.stderr)
        sys.exit(2)

    spec_path = Path(sys.argv[1])
    headed = "--headed" in sys.argv[2:]
    spec = json.loads(spec_path.read_text())
    result = publish_thread(spec["main"], spec.get("replies", []), headless=not headed)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()

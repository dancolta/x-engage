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

PAUSED_FLAG = Path.home() / ".x-engage" / "PAUSED"
INCIDENT_DIR = Path.home() / "Downloads"


def _write_paused(reason: str) -> None:
    PAUSED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    PAUSED_FLAG.write_text(f"{int(time.time())}: {reason}\n")


def _profile_dir() -> Path:
    raw = config.env("X_PROFILE_DIR", "~/.x-engage/chrome-profile")
    p = Path(os.path.expanduser(raw or ""))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _human_type(locator, text: str) -> None:
    """Type text char-by-char with humanized delays + occasional pause."""
    for ch in text:
        locator.type(ch, delay=random.uniform(40, 120))
        if random.random() < 0.05:
            time.sleep(random.uniform(0.25, 0.9))


# --- Humanization: pacing + passive actions -------------------------------
#
# Added 2026-05-25 after X labeled the account for platform manipulation.
# Goal: break the metronome-publish + 100%-reply-traffic fingerprint that
# the spam classifier was matching. Everything here is best-effort —
# any failure is logged and swallowed; passive actions must NEVER affect
# publish status.

def _hcfg(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the humanization sub-block with safe defaults if missing."""
    return settings.get("humanization") or {}


def _compute_gap(settings: dict[str, Any]) -> int:
    """Wait time between publishes. Exponential by default; occasional long pause.

    Replaces the legacy `min_gap + random.randint(0, 30)` metronome. Real users
    don't space actions on a clock — they cluster, drift, then go quiet.
    """
    h = _hcfg(settings)
    floor = int(h.get("gap_floor_sec", settings.get("min_gap_between_publishes_sec", 90)))
    ceiling = int(h.get("gap_ceiling_sec", 900))
    long_pct = float(h.get("long_pause_pct", 0.0))

    # Occasional long "distraction" pause — humans get pulled away from the app
    if long_pct > 0 and random.random() < long_pct:
        lp = h.get("long_pause_range_sec", [300, 1200])
        lo, hi = int(lp[0]), int(lp[1])
        return random.randint(max(floor, lo), max(floor, hi))

    dist = h.get("gap_distribution", "uniform")
    if dist == "exponential":
        mean = max(floor, int(h.get("gap_mean_sec", 240)))
        # exponential with mean = (mean - floor), then shift up by floor so
        # we respect the safety floor. Clamp to ceiling.
        raw = floor + int(random.expovariate(1.0 / max(1, mean - floor)))
        return max(floor, min(ceiling, raw))
    # legacy uniform
    return floor + random.randint(0, 30)


def _scroll_home_feed(page, seconds: float) -> None:
    """Scroll the home feed for ~`seconds` with human-ish cadence."""
    end = time.time() + seconds
    while time.time() < end:
        page.mouse.wheel(0, random.randint(200, 700))
        page.wait_for_timeout(random.randint(800, 2500))
        # Occasional scroll-back-up — humans re-read
        if random.random() < 0.15:
            page.mouse.wheel(0, -random.randint(100, 400))
            page.wait_for_timeout(random.randint(400, 1200))


def _like_random_feed_post(page) -> bool:
    """Click a like button on a random visible feed article. Returns True on success."""
    try:
        # Only target unliked buttons (data-testid='like', not 'unlike')
        likes = page.locator('article button[data-testid="like"]')
        n = likes.count()
        if n == 0:
            return False
        idx = random.randint(0, min(n - 1, 8))  # only first ~9 to stay within viewport
        btn = likes.nth(idx)
        if not btn.is_visible(timeout=1500):
            return False
        page.wait_for_timeout(random.randint(500, 1400))
        btn.click()
        page.wait_for_timeout(random.randint(400, 1100))
        return True
    except Exception:
        return False


def _view_random_profile(page) -> bool:
    """Click a random visible author link in the feed, idle, then navigate back."""
    try:
        # User name links inside articles point to /<handle>
        links = page.locator('article div[data-testid="User-Name"] a[role="link"]')
        n = links.count()
        if n == 0:
            return False
        idx = random.randint(0, min(n - 1, 6))
        link = links.nth(idx)
        if not link.is_visible(timeout=1500):
            return False
        link.click()
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        # Idle on profile — read bio, glance at posts
        page.wait_for_timeout(random.randint(2500, 6000))
        # Maybe a small scroll
        if random.random() < 0.6:
            page.mouse.wheel(0, random.randint(200, 600))
            page.wait_for_timeout(random.randint(800, 2000))
        page.go_back(wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(random.randint(800, 1800))
        return True
    except Exception:
        return False


def _weighted_choice(weights: dict[str, int]) -> str:
    items = [(k, max(0, int(v))) for k, v in weights.items()]
    total = sum(w for _, w in items)
    if total <= 0:
        return "idle"
    r = random.randint(1, total)
    acc = 0
    for k, w in items:
        acc += w
        if r <= acc:
            return k
    return items[-1][0]


def _warmup_session(page, settings: dict[str, Any]) -> None:
    """Scroll the home feed + maybe like 1-2 posts before any publish. Best-effort."""
    h = _hcfg(settings)
    if not h.get("warmup_enabled", False):
        return
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.randint(1500, 3500))
        sig = _scan_for_safety(page)
        if sig:
            log.warn("warmup_safety_signal", signal=sig)
            return
        dur_range = h.get("warmup_duration_sec", [25, 90])
        dur = random.uniform(float(dur_range[0]), float(dur_range[1]))
        _scroll_home_feed(page, dur)
        like_pct = float(h.get("warmup_like_pct", 0.0))
        if like_pct > 0 and random.random() < like_pct:
            for _ in range(random.randint(1, 2)):
                _like_random_feed_post(page)
                page.wait_for_timeout(random.randint(1500, 4000))
        log.info("warmup_done", duration_sec=round(dur, 1))
    except Exception as e:
        log.warn("warmup_failed", err=str(e))


def _interlude(page, settings: dict[str, Any]) -> None:
    """Insert N passive actions between publishes. Best-effort, swallow failures.

    Action counts come from `humanization.interlude_actions_per_reply`. Action
    mix is weighted by `humanization.interlude_action_weights`. Each action is
    independent; if one fails (selector miss, network blip) we move on.
    """
    h = _hcfg(settings)
    if not h.get("interlude_enabled", False):
        return
    rng = h.get("interlude_actions_per_reply", [2, 5])
    n = random.randint(int(rng[0]), int(rng[1]))
    weights = h.get("interlude_action_weights", {
        "scroll_home": 5, "like_feed": 2, "view_profile": 1, "idle": 3
    })

    # Most actions need to be on /home; navigate once if we're elsewhere.
    try:
        if "/home" not in (page.url or ""):
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(random.randint(1200, 2800))
    except Exception as e:
        log.warn("interlude_nav_failed", err=str(e))
        return

    actions_done = []
    for _ in range(n):
        kind = _weighted_choice(weights)
        try:
            if kind == "scroll_home":
                _scroll_home_feed(page, random.uniform(4, 14))
            elif kind == "like_feed":
                _like_random_feed_post(page)
            elif kind == "view_profile":
                _view_random_profile(page)
            else:  # idle
                page.wait_for_timeout(random.randint(2000, 9000))
            actions_done.append(kind)
        except Exception as e:
            log.warn("interlude_action_failed", kind=kind, err=str(e))
    log.info("interlude_done", actions=actions_done)


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

        # Warmup: scroll the home feed (and maybe like 1-2 posts) before any
        # publish. Breaks the "open → immediately reply" automation signature.
        _warmup_session(page, settings)

        for i, row in enumerate(rows):
            if config.is_halted():
                log.warn("publish_halted_mid_batch")
                break
            if i > 0:
                # Interlude: scroll/like-feed/view-profile/idle between replies.
                # Replaces the metronome cadence with mixed-behavior traffic.
                _interlude(page, settings)
                gap = _compute_gap(settings)
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


def _maybe_like_parent(page, row: dict[str, Any]) -> None:
    """Click the parent tweet's like button with configurable probability.

    Probability comes from settings.yml `engagement.like_parent_pct` (0.0–1.0,
    default 0.0). Set to 0.5 for "every second post on average" — randomness
    avoids the deterministic tick-tock pattern that's itself a detection signal.

    Skips if:
      - probability roll fails
      - like button not visible (parent post deleted or page mid-load)
      - already liked (data-testid switches from 'like' to 'unlike' — never
        un-likes by accident)

    Errors are logged but never bubble up — a like failure must not affect
    publish status. The reply has already shipped at this point.
    """
    try:
        pct = float((config.settings().get("engagement") or {}).get("like_parent_pct", 0.0))
    except (TypeError, ValueError):
        pct = 0.0
    if pct <= 0:
        return
    if random.random() >= pct:
        return  # rolled "skip"
    try:
        # Parent tweet is the first <article> on the page. Its like button has
        # data-testid="like" (unliked) or "unlike" (already liked). We only
        # touch "like" — never accidentally un-like an already-liked post.
        like_btn = page.locator('article').first.locator('button[data-testid="like"]').first
        # Short visibility check; if not present in 2s it's not coming
        if like_btn.is_visible(timeout=2000):
            # Brief humanized pause before clicking — read-then-like cadence
            page.wait_for_timeout(random.randint(600, 1400))
            like_btn.click()
            page.wait_for_timeout(random.randint(400, 900))
            log.info("liked_parent", id=row["id"])
    except Exception as e:
        log.warn("like_parent_failed", id=row["id"], err=str(e))


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
        # Selector timeout bumped 4s → 8s on 2026-05-20: slow X loads were
        # causing "reply box not found" failures even on valid posts. With
        # 3 selectors × 8s = up to 24s per publish attempt; still well
        # under the 60s tick interval and the 90s publish gap.
        for selector in (
            'div[data-testid="tweetTextarea_0"]',
            'div[aria-label*="Post your reply"]',
            'div[aria-label*="Reply"]',
        ):
            try:
                page.wait_for_selector(selector, timeout=8000)
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
        # Optionally like the parent tweet (configurable probability) — addresses
        # the "pure-reply action profile" risk surfaced by shadowban research.
        # Wrapped in try/except so a like failure never affects publish status.
        _maybe_like_parent(page, row)
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

"""One-time interactive login for the Playwright Chromium profile.

Launches a visible browser, navigates to x.com/login, then waits for you to
close the window. When you close it, your session is saved in the persistent
profile dir and subsequent headless `publish` runs will reuse it.

Usage:
    python3 -m scripts.login
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Allow `python3 -m scripts.login` from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lib import config  # loads .env and SSL certs

PROFILE = Path(os.path.expanduser(config.env("X_PROFILE_DIR", "~/.x-engage/chrome-profile") or ""))


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[fail] playwright not installed. Run: pip install playwright && playwright install chromium")
        return 1

    PROFILE.mkdir(parents=True, exist_ok=True)
    print(f"[info] Opening Chromium with profile dir: {PROFILE}")
    print("[info] Log into x.com in the browser. When done, just close the window.")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://x.com/login")

        # Poll until the user closes the browser window
        while True:
            try:
                if not ctx.pages:
                    break
                # Cheap liveness check
                ctx.pages[0].title()
                time.sleep(2)
            except Exception:
                break

        # Try a clean shutdown if context is still alive
        try:
            ctx.close()
        except Exception:
            pass

    # Verify a session cookie landed (Playwright Chromium stores it here, not in Default/Network/)
    cookies_db = PROFILE / "Default" / "Cookies"
    if cookies_db.exists():
        print(f"[ok] Profile saved at {PROFILE}. publish runs will reuse this session.")
        return 0
    print("[warn] No cookies DB found yet — did you log in fully? Re-run if needed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

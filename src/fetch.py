"""Fetch timetable data from ManageBac.

Two source modes:

1. ``ical_feed`` — if MANAGEBAC_ICAL_URL is set, we fetch ManageBac's official
   "Subscribe to Calendar" iCal feed directly (the URL contains an auth token).
   No login/password needed. This feed carries events/deadlines/tasks.

2. ``browser`` — Playwright logs in with username/password and scrapes the
   Timetable page (the weekly class schedule, which is NOT in the iCal feed).
   This is the primary path for class timetables.

Credentials are only ever read from the environment / GitHub Actions secrets.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List
from urllib import request

log = logging.getLogger("fetch")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# --- Mode 1: iCal feed ------------------------------------------------------

def fetch_ical(url: str) -> str:
    req = request.Request(url, headers={"User-Agent": UA})
    with request.urlopen(req, timeout=90) as resp:
        data = resp.read()
    charset = resp.headers.get_content_charset() or "utf-8"
    return data.decode(charset, "replace")


# --- Mode 2: browser --------------------------------------------------------

def _dump_dir(cfg) -> Path:
    d = Path("debug")
    d.mkdir(exist_ok=True)
    return d


def _dump(cfg, name: str, content: str) -> None:
    (_dump_dir(cfg) / name).write_bytes(content.encode("utf-8"))


def _accept_cookies(page) -> None:
    """Dismiss ManageBac's cookie-consent modal if present."""
    from playwright.sync_api import TimeoutError as PWTimeout
    for label in ("Accept All", "Accept Only Necessary"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(500)
                return
        except PWTimeout:
            continue
        except Exception:  # noqa: BLE001
            continue


def _login(page, cfg) -> None:
    page.goto(cfg.login_url, wait_until="domcontentloaded", timeout=60000)
    _accept_cookies(page)

    page.fill("#session_login", cfg.username or "")
    page.fill("#session_password", cfg.password or "")

    # Submitting the form sends the hidden authenticity_token automatically.
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
        page.click("input[name='commit']")
    page.wait_for_timeout(3000)

    # If we're still on a login/session page, login failed.
    if "/login" in page.url or "/sessions" in page.url:
        raise RuntimeError(
            "Login failed — still on the login page. Check credentials, or a "
            "CAPTCHA/security prompt may have appeared (we will NOT bypass it)."
        )
    log.info("Logged in successfully as user (redacted).")


def _go_next_week(page) -> bool:
    """Navigate to the next week using ManageBac's own 'Next' link."""
    link = page.locator("a[href*='direction=future']").first
    if link.count() == 0:
        return False
    href = link.get_attribute("href")
    if not href:
        return False
    page.goto(href, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    return True


def fetch_browser(cfg) -> Dict:
    from playwright.sync_api import sync_playwright

    captured: List[Dict] = []
    weeks: List[Dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
            locale="en-GB",
        )
        page = context.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers.get("content-type") or "").lower()
                if "json" in ct or resp.url.lower().endswith(".json"):
                    captured.append({"url": resp.url, "body": resp.json()})
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)

        try:
            _login(page, cfg)
            page.goto(cfg.timetable_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            for k in range(max(1, cfg.weeks_ahead)):
                html = page.content()
                weeks.append({"week": k, "url": page.url, "html": html})
                if cfg.debug:
                    _dump(cfg, f"week_{k}.html", html)
                log.info("Captured week %d (%s)", k, page.url)
                if k < cfg.weeks_ahead - 1:
                    if not _go_next_week(page):
                        log.warning("Could not advance to next week; stopping after %d week(s).", k + 1)
                        break
        finally:
            if cfg.debug:
                try:
                    page.screenshot(path=str(_dump_dir(cfg) / "timetable.png"), full_page=True)
                except Exception:  # noqa: BLE001
                    pass
                _dump(cfg, "captured.json", json.dumps(captured, ensure_ascii=False, indent=2, default=str))
            browser.close()

    if cfg.debug:
        log.info("Debug dumps written to ./debug/ (HTML per week, captured.json, screenshot).")

    return {"weeks": weeks, "json": captured}

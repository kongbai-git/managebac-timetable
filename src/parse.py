"""Parsing: turn raw fetched data into normalized calendar events.

For the iCal-feed mode we re-wrap ManageBac's existing ICS (it is already valid
RFC 5545) to add VTIMEZONE, METHOD:PUBLISH and X-WR-CALNAME, keeping each
event's own stable UID.

For the browser mode we extract dated events from the timetable HTML (and any
captured JSON), then map period names to clock times using periods.json.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Dict, List

log = logging.getLogger("parse")


# --- Generic ICS helpers (used by the iCal-feed mode) -----------------------

def unfold(text: str) -> List[str]:
    """RFC 5545 line unfolding."""
    lines: List[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def split_components(text: str) -> tuple[List[str], List[List[str]]]:
    """Return (vcalendar header lines, list of VEVENT blocks as line-lists)."""
    lines = unfold(text)
    header: List[str] = []
    vevents: List[List[str]] = []
    current: List[str] | None = None
    in_vevent = False

    for ln in lines:
        if ln == "BEGIN:VEVENT":
            in_vevent = True
            current = [ln]
            continue
        if ln == "END:VEVENT" and in_vevent:
            current.append(ln)
            vevents.append(current)
            in_vevent = False
            current = None
            continue
        if in_vevent and current is not None:
            current.append(ln)
        elif not in_vevent:
            if ln not in ("END:VCALENDAR", "BEGIN:VCALENDAR"):
                header.append(ln)
    return header, vevents


def rewrap_ical(text: str, tz: str, calname: str) -> str:
    """Rebuild a VCALENDAR around ManageBac's existing VEVENTs."""
    from . import icsgen

    _, vevents = split_components(text)
    if not vevents:
        raise RuntimeError("iCal feed contained no VEVENTs (empty or auth token invalid?).")

    out = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ManageBac Timetable Sync//managebac-timetable//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{icsgen.escape_text(calname)}",
        f"X-WR-TIMEZONE:{tz}",
    ]
    out += icsgen.vtimezone_lines(tz)
    for block in vevents:
        out.extend(block)
    out.append("END:VCALENDAR")

    return icsgen.CRLF.join(icsgen.fold(ln) for ln in out) + icsgen.CRLF


# --- Mode 2: timetable HTML/JSON extraction ---------------------------------

def _norm_period(name: str) -> str:
    """Normalize a period label so it can be matched against periods.json keys."""
    n = re.sub(r"\s+", " ", (name or "").strip()).lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _match_period(period_name: str, periods: Dict[str, Dict[str, str]]):
    """Fuzzy-match a scraped period label to a periods.json key."""
    target = _norm_period(period_name)
    # exact (normalized) match first
    for key, val in periods.items():
        if _norm_period(key) == target:
            return val
    # substring match
    for key, val in periods.items():
        nk = _norm_period(key)
        if nk and (nk in target or target in nk):
            return val
    return None


def _build_event(date_str: str, period_times: Dict, summary: str,
                 teacher: str = "", location: str = "", notes: str = "") -> Dict:
    return {
        "date": date_str,
        "start": period_times.get("start", ""),
        "end": period_times.get("end", ""),
        "summary": summary,
        "teacher": teacher,
        "location": location,
        "description": notes,
        "all_day": False,
    }


def extract_from_html(html: str, periods: Dict[str, Dict[str, str]]) -> List[Dict]:
    """Best-effort extraction of dated class blocks from timetable HTML.

    NOTE: ManageBac renders the timetable as a period x date grid. The exact
    DOM varies by school/template, so this parser is deliberately generic and
    may need selector tuning against a real DEBUG dump. See README.md.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("beautifulsoup4 not installed; skipping HTML extraction.")
        return []

    soup = BeautifulSoup(html, "html.parser")
    events: List[Dict] = []

    # 1) Find all date headings (cells/headers whose text or data-* hold a date).
    date_cells = {}
    date_re = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
    for el in soup.find_all(["th", "td", "div", "span"]):
        txt = " ".join(el.get_text(" ", strip=True).split())
        if not txt:
            continue
        m = date_re.search(txt)
        if m:
            try:
                iso = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            except ValueError:
                continue
            # record the position so we can associate blocks by column index
            date_cells[id(el)] = iso

    # 2) Find class blocks via a set of common selectors.
    block_selectors = [
        "[data-class-id]", "[data-course]", "[data-event]",
        ".timetable-event", ".lesson", ".class-block", ".event-block",
        ".fc-event", "[class*='timetable'] [class*='block']",
        "[class*='period'][class*='item']",
    ]
    seen = set()
    for sel in block_selectors:
        try:
            els = soup.select(sel)
        except Exception:  # noqa: BLE001
            continue
        for el in els:
            if id(el) in seen:
                continue
            seen.add(id(el))
            text = " ".join(el.get_text(" ", strip=True).split())
            if not text:
                continue
            # Try data-* attributes first (most reliable when present)
            date_str = (el.get("data-date") or el.get("data-day") or "")
            period_name = (el.get("data-period") or el.get("data-period-name") or "")
            summary = (el.get("data-course") or el.get("data-class")
                       or el.get("data-title") or el.get("title") or "")
            location = (el.get("data-location") or el.get("data-room") or "")
            teacher = (el.get("data-teacher") or "")

            if not date_str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
                # fall back to nearest date heading (same column) — heuristic
                date_str = _nearest_date(el, date_cells)
            if not summary:
                summary = text
            if not date_str:
                continue

            pt = _match_period(period_name, periods) if period_name else None
            if pt is None and period_name:
                log.warning("Period not found in periods.json: %r", period_name)
            if pt is None:
                # Without a period time we cannot place the event on the clock.
                continue

            events.append(_build_event(date_str, pt, summary, teacher, location))

    # dedupe by stable key
    return _dedupe(events)


def _nearest_date(el, date_cells) -> str:
    # Simple heuristic: walk up/around for an element we already tagged as a date.
    node = el
    for _ in range(6):
        if id(node) in date_cells:
            return date_cells[id(node)]
        node = node.parent
        if node is None:
            break
    return ""


def extract_from_json(payloads: List[Dict], periods: Dict[str, Dict[str, str]]) -> List[Dict]:
    """Recursively search captured JSON for objects that look like timetable events.

    A candidate object has a title/class-like field AND a date and/or period/time
    field. This is deliberately generic — tune the key sets below against a real
    DEBUG dump (captured.json).
    """
    title_keys = {"name", "title", "course", "class", "class_name", "subject", "summary", "lesson"}
    date_keys = {"date", "day", "start_date", "event_date"}
    period_keys = {"period", "period_name", "period_title", "block"}
    start_keys = {"start", "start_time", "starts_at"}
    end_keys = {"end", "end_time", "ends_at"}
    teacher_keys = {"teacher", "teacher_name", "instructor"}
    loc_keys = {"location", "room", "classroom", "venue"}

    def looks_like_event(obj) -> bool:
        if not isinstance(obj, dict):
            return False
        keys = {str(k).lower() for k in obj.keys()}
        return bool(keys & title_keys) and bool(keys & (date_keys | period_keys | start_keys))

    found: List[Dict] = []

    def walk(node):
        if isinstance(node, dict):
            if looks_like_event(node):
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for payload in payloads:
        body = payload.get("body")
        if body is not None:
            walk(body)

    events: List[Dict] = []
    for obj in found:
        def first(*key_groups):
            for kg in key_groups:
                for k in kg:
                    for ok, v in obj.items():
                        if str(ok).lower() == k and v not in (None, ""):
                            return v
            return ""

        summary = str(first(title_keys))
        date_str = str(first(date_keys))
        period_name = str(first(period_keys))
        start_raw = str(first(start_keys))
        end_raw = str(first(end_keys))
        teacher = str(first(teacher_keys))
        location = str(first(loc_keys))

        # date may come as a timestamp; keep only YYYY-MM-DD prefix
        m = re.search(r"(20\d{2}-\d{2}-\d{2})", date_str)
        if m:
            date_str = m.group(1)
        elif not date_str:
            continue

        if start_raw and end_raw:
            pt = {"start": _to_hhmmss(start_raw), "end": _to_hhmmss(end_raw)}
        else:
            pt = _match_period(period_name, periods) if period_name else None
            if pt is None:
                continue

        events.append(_build_event(date_str, pt, summary, teacher, location))
    return _dedupe(events)


def _to_hhmmss(raw: str) -> str:
    """Normalize '09:30', '09:30:00', '2026-09-12T09:30:00+08:00' to HH:MM:SS."""
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", raw)
    if not m:
        return "00:00:00"
    hh = int(m.group(1)) % 24
    mm = m.group(2)
    ss = m.group(3) or "00"
    return f"{hh:02d}:{mm}:{ss}"


def _dedupe(events: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for ev in events:
        key = (ev["date"], ev["start"], ev["end"], ev["summary"], ev["location"])
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def extract_events(raw: Dict, cfg) -> List[Dict]:
    """Top-level extractor for browser mode."""
    from . import config as cfgmod

    periods = cfgmod.load_periods(cfg.periods_file)

    events: List[Dict] = []
    for week in raw.get("weeks", []):
        html = week.get("html", "")
        events.extend(extract_from_html(html, periods))

    json_events = extract_from_json(raw.get("json", []), periods)
    if json_events:
        log.info("Extracted %d events from captured JSON.", len(json_events))
        # JSON events usually have explicit times — prefer them over HTML guesses.
        if not events:
            events = json_events
        else:
            # merge, dedupe again
            events = _dedupe(events + json_events)

    if not events:
        raise RuntimeError(
            "No timetable events extracted. Run with DEBUG=1 to dump HTML/JSON "
            "into ./debug/, inspect the structure, and tune the parser in "
            "src/parse.py. (Also confirm MANAGEBAC_TIMETABLE_PATH points at the "
            "real timetable URL.)"
        )
    log.info("Total unique events after dedupe: %d", len(events))
    return events

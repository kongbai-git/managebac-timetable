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
from html import unescape
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


MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _parse_date_header(text: str, year: int):
    """'Sep 7, Mon Rotation Day 6' -> '2026-09-07'."""
    m = re.search(r"([A-Za-z]{3})\s+(\d{1,2})", text)
    if not m:
        return None
    mon = MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    return f"{year}-{mon:02d}-{int(m.group(2)):02d}"


def _parse_time_range(text: str):
    """'8:10 AM - 9:10 AM' -> ('08:10:00', '09:10:00')."""
    m = re.search(
        r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*(\d{1,2}):(\d{2})\s*(AM|PM)",
        text, re.IGNORECASE,
    )
    if not m:
        return None

    def to24(h, mi, ap):
        h = int(h)
        ap = ap.upper()
        if ap == "PM" and h != 12:
            h += 12
        elif ap == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mi}:00"

    return (to24(m.group(1), m.group(2), m.group(3)),
            to24(m.group(4), m.group(5), m.group(6)))


def _strip_tags(text: str) -> str:
    return unescape(" ".join(re.sub(r"<[^>]+>", " ", text).split()))


def _parse_block(block_html: str, date_str: str, period_name: str, periods) -> Dict:
    """Parse one a.f-timetable-item block (HTML string) into an event dict."""
    name_m = re.search(r"<(?:p|h6)[^>]*fw-semibold[^>]*>(.*?)</(?:p|h6)>", block_html, re.S)
    if not name_m:
        return None
    summary = _strip_tags(name_m.group(1))
    if not summary or _is_non_class(summary):
        return None

    teacher = ""
    location = ""
    for m in re.finditer(r"<p([^>]*)>(.*?)</p>", block_html, re.S):
        attrs = m.group(1)
        txt = _strip_tags(m.group(2))
        if "fw-semibold" in attrs:
            continue  # course name, already captured
        if "mt-1" in attrs or txt.startswith("Year "):
            continue  # year-group line
        if "text-truncate" in attrs:
            teacher = txt
        else:
            location = txt

    if "|" in teacher:
        teacher = teacher.split("|")[0].strip()  # "Full Name | Preferred" -> keep full name

    time_m = re.search(r"<small[^>]*>(.*?)</small>", block_html, re.S)
    time_range = _parse_time_range(_strip_tags(time_m.group(1))) if time_m else None
    if time_range:
        start, end = time_range
    else:
        pt = _match_period(period_name, periods)
        if not pt:
            return None
        start, end = pt["start"], pt["end"]

    return {
        "date": date_str,
        "start": start,
        "end": end,
        "summary": summary,
        "teacher": teacher,
        "location": location,
        "description": "",
        "all_day": False,
    }


def extract_from_html(html: str, periods: Dict[str, Dict[str, str]]) -> List[Dict]:
    """Parse ManageBac's server-rendered timetable table (stdlib only).

    The table has a thead with one <th> per weekday (e.g. "Sep 7, Mon Rotation
    Day 6") and tbody rows where the row's <th> is the period name and each
    <td> holds zero or more class blocks (a.f-timetable-item). A class block
    carries the time, course name, teacher and room directly.
    """
    ym = re.search(r"start_date=(\d{4})-\d{2}-\d{2}", html)
    year = int(ym.group(1)) if ym else datetime.now().year

    headers: List[str] = []
    thead = re.search(r"<thead.*?</thead>", html, re.S)
    if thead:
        for i, th in enumerate(re.findall(r"<th[^>]*>(.*?)</th>", thead.group(0), re.S)):
            if i == 0:
                headers.append("")  # "Period" corner cell
                continue
            headers.append(_parse_date_header(_strip_tags(th), year) or "")

    tbody = re.search(r"<tbody.*?</tbody>", html, re.S)
    events: List[Dict] = []
    if not tbody:
        return events

    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(0), re.S):
        th_m = re.search(r"<th[^>]*>(.*?)</th>", tr, re.S)
        period_name = _strip_tags(th_m.group(1)) if th_m else ""
        for j, td in enumerate(re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)):
            date_str = headers[j + 1] if j + 1 < len(headers) else ""
            if not date_str:
                continue
            for block in re.findall(r"<a[^>]*f-timetable-item[^>]*>.*?</a>", td, re.S):
                ev = _parse_block(block, date_str, period_name, periods)
                if ev:
                    events.append(ev)

    return _dedupe(events)


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


def _is_non_class(summary: str) -> bool:
    """True for break/lunch blocks that should never become calendar events."""
    s = (summary or "").strip().lower()
    return s == "break" or "lunch" in s or "recess" in s


def _apply_class_filter(events: List[Dict], include: List[str], exclude: List[str]) -> List[Dict]:
    """Filter events by class-name whitelist/blacklist (substring, case-insensitive)."""
    if not include and not exclude:
        return events
    out = []
    for ev in events:
        s = (ev.get("summary") or "").lower()
        if include and not any(i.lower() in s for i in include):
            continue
        if exclude and any(e.lower() in s for e in exclude):
            continue
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

    # Drop non-class blocks (lunch/break/recess) and apply class-name filters.
    events = [e for e in events if not _is_non_class(e.get("summary") or "")]
    events = _apply_class_filter(events, cfg.class_include, cfg.class_exclude)

    if not events:
        raise RuntimeError(
            "No timetable events extracted. Run with DEBUG=1 to dump HTML/JSON "
            "into ./debug/, inspect the structure, and tune the parser in "
            "src/parse.py. (Also confirm MANAGEBAC_TIMETABLE_PATH points at the "
            "real timetable URL.)"
        )
    log.info("Total unique events after dedupe: %d", len(events))
    return events

"""RFC 5545 iCalendar (ICS) generation.

Self-contained (stdlib only). Handles:
- VTIMEZONE for Asia/Shanghai (and generic fixed-offset zones)
- Stable UIDs derived from a hash of date+time+course+location
- TEXT escaping (backslash, comma, semicolon, newline)
- 75-octet line folding (applied per physical line, UTF-8 safe)
- Timed events (DTSTART/DTEND;TZID=...) and all-day events (VALUE=DATE)

Design note: components are built as LISTS of single physical lines (no embedded
newlines); build_ical() folds each line individually and joins with CRLF.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List

CRLF = "\r\n"


# --- VTIMEZONE -------------------------------------------------------------

def vtimezone_lines(tz: str) -> List[str]:
    """Return the VTIMEZONE component as a list of physical lines."""
    if tz == "Asia/Shanghai":
        return [
            "BEGIN:VTIMEZONE",
            "TZID:Asia/Shanghai",
            "X-LIC-LOCATION:Asia/Shanghai",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            "TZOFFSETFROM:+0800",
            "TZOFFSETTO:+0800",
            "TZNAME:CST",
            "END:STANDARD",
            "END:VTIMEZONE",
        ]
    # Generic fixed-offset zone, e.g. "UTC+08:00" or "Etc/GMT+8"
    offset = tz.replace("UTC", "").replace("Etc/GMT", "")
    if offset.startswith("+") or offset.startswith("-"):
        off = offset.replace(":", "")
        tzname = "UTC" + off
        return [
            "BEGIN:VTIMEZONE",
            f"TZID:{tz}",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            f"TZOFFSETFROM:{off}",
            f"TZOFFSETTO:{off}",
            f"TZNAME:{tzname}",
            "END:STANDARD",
            "END:VTIMEZONE",
        ]
    raise ValueError(f"Unsupported timezone for VTIMEZONE generation: {tz!r}")


# --- Helpers ---------------------------------------------------------------

def escape_text(value: str) -> str:
    """RFC 5545 TEXT escaping."""
    if value is None:
        return ""
    value = value.replace("\\", "\\\\")
    value = value.replace(";", "\\;")
    value = value.replace(",", "\\,")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\n", "\\n")
    return value


def fold(line: str) -> str:
    """Fold a single physical line to <=75 octets, UTF-8 safe (RFC 5545 §3.1).

    Continuation lines begin with a space, which is included in the 75-octet
    count, per common practice.
    """
    if len(line.encode("utf-8")) <= 75:
        return line
    out: List[str] = []
    remaining = line
    while True:
        b = remaining.encode("utf-8")
        if len(b) <= 75:
            out.append(remaining)
            break
        # Largest char-prefix whose UTF-8 encoding fits in 75 octets.
        lo, hi = 0, len(remaining)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if len(remaining[:mid].encode("utf-8")) <= 75:
                lo = mid
            else:
                hi = mid - 1
        cut = lo if lo > 0 else 1
        out.append(remaining[:cut])
        remaining = " " + remaining[cut:]
    return CRLF.join(out)


def make_uid(event: Dict[str, str]) -> str:
    """Stable UID: hash of date+start+end+summary+location.

    Same inputs => same UID => Apple Calendar updates events in place instead
    of duplicating them across refreshes.
    """
    key = "|".join(
        [
            event.get("date", ""),
            event.get("start", ""),
            event.get("end", ""),
            event.get("summary", ""),
            event.get("location", ""),
        ]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"{digest}@managebac-timetable"


def _fmt_dt_local(date_str: str, time_str: str) -> str:
    """'2026-09-12' + '08:00:00' -> '20260912T080000'."""
    d = date_str.replace("-", "")
    t = (time_str or "00:00:00").replace(":", "")
    t = t[:6].ljust(6, "0")
    return f"{d}T{t}"


def _next_day(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def vevent_lines(event: Dict[str, str], tz: str) -> List[str]:
    """Return a single VEVENT component as a list of physical lines."""
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VEVENT", "UID:" + make_uid(event), "DTSTAMP:" + dtstamp]

    if event.get("all_day") in (True, "True", "1", "true"):
        lines.append("DTSTART;VALUE=DATE:" + event["date"].replace("-", ""))
        lines.append("DTEND;VALUE=DATE:" + _next_day(event["date"]).replace("-", ""))
    else:
        lines.append(f"DTSTART;TZID={tz}:" + _fmt_dt_local(event["date"], event.get("start", "")))
        lines.append(f"DTEND;TZID={tz}:" + _fmt_dt_local(event["date"], event.get("end", "")))

    if event.get("summary"):
        lines.append("SUMMARY:" + escape_text(event["summary"]))
    if event.get("location"):
        lines.append("LOCATION:" + escape_text(event["location"]))

    desc_parts = []
    if event.get("teacher"):
        desc_parts.append("Teacher: " + event["teacher"])
    if event.get("description"):
        desc_parts.append(event["description"])
    if event.get("notes"):
        desc_parts.append(event["notes"])
    if desc_parts:
        lines.append("DESCRIPTION:" + escape_text("\n".join(desc_parts)))

    if event.get("categories"):
        lines.append("CATEGORIES:" + escape_text(event["categories"]))

    lines.append("STATUS:" + str(event.get("status") or "CONFIRMED"))
    lines.append("SEQUENCE:0")
    lines.append("END:VEVENT")
    return lines


def build_ical(
    events: List[Dict[str, str]],
    tz: str = "Asia/Shanghai",
    calname: str = "ManageBac Timetable",
    prodid: str = "-//ManageBac Timetable Sync//managebac-timetable//EN",
) -> str:
    """Build a complete RFC 5545 VCALENDAR string from a list of events."""
    lines: List[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + prodid,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + escape_text(calname),
        "X-WR-TIMEZONE:" + tz,
    ]
    lines += vtimezone_lines(tz)
    for ev in events:
        lines += vevent_lines(ev, tz)
    lines.append("END:VCALENDAR")

    return CRLF.join(fold(ln) for ln in lines) + CRLF

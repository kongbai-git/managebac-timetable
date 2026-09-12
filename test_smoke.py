"""Smoke test: import all modules, exercise ICS generation + rewrap + UID stability."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, icsgen, parse, publish, notify  # noqa: E402

# 1) UID stability: same event -> same UID across calls
ev = {"date": "2026-09-14", "start": "08:25:00", "end": "09:05:00",
      "summary": "IB DP Mathematics HL", "location": "Room 301"}
assert icsgen.make_uid(ev) == icsgen.make_uid(ev), "UID not stable"
uid_a = icsgen.make_uid(ev)
ev2 = dict(ev, location="Room 302")
assert icsgen.make_uid(ev2) != uid_a, "UID should change when location changes"
print("PASS: UID stable + sensitive to location")

# 2) build_ical full round-trip
ics = icsgen.build_ical([ev], tz="Asia/Shanghai")
for required in ["BEGIN:VCALENDAR", "VERSION:2.0", "CALSCALE:GREGORIAN",
                 "X-WR-CALNAME:ManageBac Timetable", "BEGIN:VTIMEZONE",
                 "TZID:Asia/Shanghai", "DTSTART;TZID=Asia/Shanghai:20260914T082500",
                 "END:VCALENDAR"]:
    assert required in ics, f"missing {required}"
assert "UID:" + uid_a in ics
print("PASS: build_ical structure + DTSTART TZID format")

# 3) rewrap_ical (iCal-feed mode): re-wrap a ManageBac-style feed
sample_feed = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//ManageBac//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:orig-123@managebac\r\n"
    "DTSTART;TZID=Asia/Shanghai:20260914T090000\r\n"
    "DTEND;TZID=Asia/Shanghai:20260914T100000\r\n"
    "SUMMARY:Mock exam\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)
rewrapped = parse.rewrap_ical(sample_feed, "Asia/Shanghai", "ManageBac Timetable")
assert "X-WR-CALNAME:ManageBac Timetable" in rewrapped
assert "BEGIN:VTIMEZONE" in rewrapped
assert "UID:orig-123@managebac" in rewrapped, "original UID must be preserved"
assert rewrapped.count("BEGIN:VEVENT") == 1
print("PASS: rewrap_ical preserves events + adds VTIMEZONE/X-WR-CALNAME")

# 4) config loading (no secrets needed for these fields)
cfg = config.load_config()
assert cfg.base_url == "https://ycishk.managebac.com"
assert cfg.source_mode in ("browser", "ical_feed")
print("PASS: config defaults (base_url, tz, source_mode =", cfg.source_mode + ")")

# 5) escape_text correctness
assert icsgen.escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
print("PASS: escape_text handles comma/semicolon/backslash/newline")

print("\nALL SMOKE TESTS PASSED")

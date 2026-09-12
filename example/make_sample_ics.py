"""Generate example/managebac_timetable.ics using the real src.icsgen module.

This is a runnable reference for the event dict schema. The data below is
FICTIONAL sample data for illustration only.
Run:  python example/make_sample_ics.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import icsgen  # noqa: E402

# Week of Monday 2026-09-14 (sample — replace with real data)
EVENTS = [
    # Monday
    {"date": "2026-09-14", "start": "08:25:00", "end": "09:05:00",
     "summary": "IB DP Mathematics HL", "teacher": "Mr. Chen", "location": "Room 301"},
    {"date": "2026-09-14", "start": "09:10:00", "end": "09:50:00",
     "summary": "IB DP Biology", "teacher": "Ms. Lam", "location": "Lab 2"},
    {"date": "2026-09-14", "start": "10:10:00", "end": "10:50:00",
     "summary": "English A: Literature", "teacher": "Dr. Wong", "location": "Room 210"},
    {"date": "2026-09-14", "start": "10:55:00", "end": "11:35:00",
     "summary": "Theory of Knowledge", "teacher": "Ms. Zhang", "location": "Room 118"},
    # Tuesday
    {"date": "2026-09-15", "start": "08:25:00", "end": "09:05:00",
     "summary": "IB DP Chemistry", "teacher": "Dr. Ng", "location": "Lab 1"},
    {"date": "2026-09-15", "start": "09:10:00", "end": "09:50:00",
     "summary": "IB DP Economics", "teacher": "Mr. Ho", "location": "Room 405",
     "description": "Bring textbook; mock exam on Friday, Sep 18, 2026"},
    {"date": "2026-09-15", "start": "10:10:00", "end": "10:50:00",
     "summary": "Chinese A: Language & Literature", "teacher": "Ms. Lau", "location": "Room 220"},
    # Wednesday — all-day CAS event
    {"date": "2026-09-16", "all_day": True,
     "summary": "CAS Service Day", "teacher": "Mr. Tang",
     "description": "Off-campus service; meet at 07:45 in the atrium",
     "location": "Community Centre"},
    # Wednesday
    {"date": "2026-09-16", "start": "13:10:00", "end": "13:50:00",
     "summary": "IB DP Physics", "teacher": "Dr. Yip", "location": "Lab 3"},
    # Thursday
    {"date": "2026-09-17", "start": "08:25:00", "end": "09:05:00",
     "summary": "IB DP Mathematics HL", "teacher": "Mr. Chen", "location": "Room 301"},
    {"date": "2026-09-17", "start": "09:10:00", "end": "09:50:00",
     "summary": "IB DP Biology", "teacher": "Ms. Lam", "location": "Lab 2"},
    # Friday — exam block, description with commas/semicolons/newline to show escaping
    {"date": "2026-09-18", "start": "08:25:00", "end": "10:50:00",
     "summary": "Extended Essay consultation", "teacher": "Dr. Wong", "location": "Library",
     "description": "Bring: draft, notes, and bibliography.\nFocus on research question; "
                   "methodology, and analysis (3 sections)."},
]

ics = icsgen.build_ical(EVENTS, tz="Asia/Shanghai", calname="ManageBac Timetable")

out = Path(__file__).resolve().parent / "managebac_timetable.ics"
out.write_bytes(ics.encode("utf-8"))
print(f"Wrote {out} ({len(EVENTS)} events, {len(ics)} chars)")

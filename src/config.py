"""Configuration loading from environment variables + a local .env file.

Secrets (username/password/notification keys) MUST come from environment
variables or GitHub Actions secrets. They are never written to logs or files.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (stdlib only) for local runs. CI uses real env vars."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


@dataclass
class Config:
    base_url: str
    username: Optional[str]
    password: Optional[str]
    tz: str
    login_url: str
    timetable_url: str
    weeks_ahead: int
    calname: str
    ics_filename: str
    publish_token: str
    out_dir: str
    periods_file: str
    debug: bool

    # Source mode: "ical_feed" or "browser"
    ical_url: Optional[str]

    # Notifications (all optional)
    notify_serverchan_sendkey: Optional[str]
    notify_pushplus_token: Optional[str]
    notify_wechat_webhook: Optional[str]
    notify_webhook_url: Optional[str]

    @property
    def source_mode(self) -> str:
        return "ical_feed" if self.ical_url else "browser"


def load_config() -> Config:
    _load_dotenv()

    base_url = (env("MANAGEBAC_BASE_URL") or "https://ycishk.managebac.com").rstrip("/")

    return Config(
        base_url=base_url,
        username=env("MANAGEBAC_USERNAME"),
        password=env("MANAGEBAC_PASSWORD"),
        tz=env("MANAGEBAC_TZ") or "Asia/Shanghai",
        login_url=base_url + (env("MANAGEBAC_LOGIN_PATH") or "/login"),
        timetable_url=base_url + (env("MANAGEBAC_TIMETABLE_PATH") or "/student/timetable"),
        weeks_ahead=int(env("MANAGEBAC_WEEKS_AHEAD") or "4"),
        calname=env("ICS_CALNAME") or "ManageBac Timetable",
        ics_filename=env("ICS_FILENAME") or "managebac_timetable.ics",
        publish_token=env("PUBLISH_TOKEN") or "",
        out_dir=env("ICS_OUT_DIR") or "dist",
        periods_file=env("PERIODS_FILE") or "periods.json",
        debug=(env("DEBUG") or "0") == "1",
        ical_url=env("MANAGEBAC_ICAL_URL"),
        notify_serverchan_sendkey=env("NOTIFY_SERVERCHAN_SENDKEY"),
        notify_pushplus_token=env("NOTIFY_PUSHPLUS_TOKEN"),
        notify_wechat_webhook=env("NOTIFY_WECHAT_WEBHOOK"),
        notify_webhook_url=env("NOTIFY_WEBHOOK_URL"),
    )


def validate_config(cfg: Config) -> None:
    """Fail fast with a clear message if required secrets are missing."""
    missing: list[str] = []
    if cfg.source_mode == "browser":
        if not cfg.username:
            missing.append("MANAGEBAC_USERNAME")
        if not cfg.password:
            missing.append("MANAGEBAC_PASSWORD")
    elif not cfg.ical_url:
        missing.append("MANAGEBAC_ICAL_URL")
    if missing:
        raise RuntimeError(
            "Missing required secrets: " + ", ".join(missing)
            + ". Set them as environment variables / GitHub Actions secrets. "
            + "Never hard-code credentials."
        )


def load_periods(path: str) -> Dict[str, Dict[str, str]]:
    """Load period -> {start,end} bell schedule from periods.json.

    Raises a clear error if missing, so the user is forced to provide their
    school's real bell schedule instead of us guessing.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(
            f"Bell schedule file '{path}' not found. Copy periods.example.json "
            "to periods.json and fill in your school's real period start/end times."
        )
    data = json.loads(p.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, str]] = {}
    for name, times in data.items():
        if name.startswith("_"):
            continue
        if not isinstance(times, dict) or "start" not in times or "end" not in times:
            continue
        out[name.strip()] = {
            "start": str(times["start"]).strip(),
            "end": str(times["end"]).strip(),
        }
    if not out:
        raise RuntimeError(f"No valid periods found in '{path}'.")
    return out

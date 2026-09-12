"""ManageBac timetable -> ICS sync. Entry point.

Usage:
    python main.py            # fetch + generate + stage ICS (and notify on failure)
    DEBUG=1 python main.py    # also dump debug HTML/JSON/screenshot to ./debug/

Run locally to verify; the GitHub Actions workflow runs this on a weekly cron
(Saturday 06:00 Asia/Shanghai = Friday 22:00 UTC) and on manual dispatch.
"""
from __future__ import annotations

import logging
import sys

from src import config as cfgmod
from src import fetch, icsgen, notify, parse, publish

log = logging.getLogger("main")


def run(cfg) -> str:
    """Produce the final ICS text. Raises on failure."""
    if cfg.source_mode == "ical_feed":
        log.info("Source mode: iCal feed (%s)", cfg.ical_url.split("?")[0])
        raw = fetch.fetch_ical(cfg.ical_url)
        return parse.rewrap_ical(raw, cfg.tz, cfg.calname)

    log.info("Source mode: browser (Playwright scrape)")
    raw = fetch.fetch_browser(cfg)
    events = parse.extract_events(raw, cfg)
    return icsgen.build_ical(events, tz=cfg.tz, calname=cfg.calname)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = cfgmod.load_config()

    try:
        cfgmod.validate_config(cfg)
        ics = run(cfg)
        rel = publish.prepare_output(cfg, ics)

        log.info("Done. ICS written (publish path: %s).", rel)
        log.info("Suggested webcal URL: %s", publish.public_url_hint(cfg, rel))

        # Informative notification only if a channel is configured.
        notify.notify(
            cfg,
            title="ManageBac Timetable synced",
            content=(
                "Timetable ICS regenerated successfully.\n"
                f"Events file: {rel}\n"
                f"Run mode: {cfg.source_mode}"
            ),
            level="info",
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("Sync failed: %s", exc)
        notify.notify_failure(cfg, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

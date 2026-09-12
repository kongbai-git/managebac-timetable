"""Stage the generated ICS for publication to GitHub Pages.

The actual upload/commit to the ``gh-pages`` branch is performed by the CI
workflow (peaceiris/actions-gh-pages), which keeps the same URL across runs.
This module only writes the file to the expected location inside dist/ and adds
a .nojekyll marker so GitHub Pages serves the raw .ics file untouched.

Privacy: if PUBLISH_TOKEN is set, the file is placed under an unguessable
subdirectory (dist/<token>/managebac_timetable.ics), so the private timetable is
not exposed at a guessable public path.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("publish")


def prepare_output(cfg, ics_text: str) -> str:
    out_dir = Path(cfg.out_dir)
    subdir = cfg.publish_token.strip("/") if cfg.publish_token else ""
    target_dir = out_dir / subdir if subdir else out_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    ics_path = target_dir / cfg.ics_filename
    ics_path.write_bytes(ics_text.encode("utf-8"))

    # Prevent Jekyll from touching the raw file.
    (out_dir / ".nojekyll").touch(exist_ok=True)

    rel = (Path(subdir) / cfg.ics_filename).as_posix() if subdir else cfg.ics_filename
    log.info("Staged ICS at %s", ics_path)
    log.info("Relative publish path: %s", rel)
    return rel


def public_url_hint(cfg, rel: str) -> str:
    # The user fills in their GitHub Pages host; this is just a reminder of the shape.
    return f"https://<username>.github.io/<repo>/{rel}"

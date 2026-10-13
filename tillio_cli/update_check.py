"""Non-blocking version update check for the Tillio CLI."""

import os
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

import httpx

from tillio_cli import __version__
from tillio_cli.config import load_config, save_config
from tillio_cli.log import logger

# Check at most once every 24 hours
CHECK_INTERVAL_HOURS = 24
PYPI_URL = "https://pypi.org/pypi/tillio-cli/json"
CHECK_TIMEOUT = 2.0  # seconds


class UpdateChecker:
    """Runs a background version check and stores the result."""

    def __init__(self):
        self.latest_version: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start a background check if conditions are met."""
        # Disabled via env var
        if os.getenv("TILLIO_NO_UPDATE_CHECK", ""):
            return
        # Not a TTY (piped, CI, etc.)
        if not sys.stderr.isatty():
            return
        # CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("GITLAB_CI"):
            return
        # Throttle: check at most once per interval
        config = load_config()
        last_check = config.get("last_update_check", "")
        if last_check:
            try:
                last_dt = datetime.fromisoformat(last_check)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                hours_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                if hours_ago < CHECK_INTERVAL_HOURS:
                    logger.debug("Update check skipped (last check %.1fh ago)", hours_ago)
                    return
            except (ValueError, TypeError):
                pass

        self._thread = threading.Thread(target=self._check, daemon=True)
        self._thread.start()

    def _check(self):
        """Fetch latest version from PyPI."""
        try:
            resp = httpx.get(PYPI_URL, timeout=CHECK_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json()
                self.latest_version = data.get("info", {}).get("version")
                logger.debug("Latest version on PyPI: %s", self.latest_version)
        except Exception as e:
            logger.debug("Update check failed: %s", e)

        # Update last check timestamp (separate try to avoid masking version data)
        try:
            config = load_config()
            config["last_update_check"] = datetime.now(timezone.utc).isoformat()
            save_config(config)
        except Exception as e:
            logger.debug("Failed to save update check timestamp: %s", e)

    def notify_if_outdated(self):
        """Print a notice to stderr if a newer version is available."""
        if self._thread:
            self._thread.join(timeout=0.5)  # wait briefly for result
        if not self.latest_version:
            return
        if self.latest_version == __version__:
            return
        # Simple version comparison: only notify if latest != current
        # (avoids complex semver parsing for dev versions)
        if __version__.startswith("0.0.0"):
            return  # dev build, skip
        import click
        click.echo(
            f"\nA new version of tillio is available: {self.latest_version} "
            f"(current: {__version__}). "
            f"Run: pip install --upgrade tillio-cli",
            err=True,
        )

"""Configuration management — reads/writes ~/.tillio/config.yaml."""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("tillio")

CONFIG_DIR = Path.home() / ".tillio"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_API_URL = os.getenv("TILLIO_API_URL", "http://localhost:8000")


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    logger.debug("Loading config from %s", CONFIG_FILE)
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict):
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)


def get_api_key() -> Optional[str]:
    return os.environ.get("TILLIO_API_KEY") or load_config().get("api_key")


def get_api_url() -> str:
    return os.environ.get("TILLIO_API_URL") or load_config().get("api_url", DEFAULT_API_URL)


def set_api_key(key: str):
    config = load_config()
    config["api_key"] = key
    save_config(config)


def set_api_url(url: str):
    config = load_config()
    config["api_url"] = url
    save_config(config)


KNOWN_CONFIG_KEYS = {"api_key", "api_url", "timeout", "last_update_check"}


def validate_config(config: dict) -> list:
    """Return a list of warning messages for invalid config entries."""
    warnings = []
    for key in config:
        if key not in KNOWN_CONFIG_KEYS:
            from difflib import get_close_matches
            matches = get_close_matches(key, KNOWN_CONFIG_KEYS, n=1, cutoff=0.5)
            msg = f"Unknown config key: '{key}'"
            if matches:
                msg += f" (did you mean '{matches[0]}'?)"
            warnings.append(msg)
    if "api_url" in config:
        url = config["api_url"]
        if isinstance(url, str) and not (url.startswith("http://") or url.startswith("https://")):
            warnings.append("api_url should start with http:// or https://")
    return warnings

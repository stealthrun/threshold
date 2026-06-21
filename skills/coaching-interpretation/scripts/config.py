"""
Optional on-disk config, so the athlete doesn't re-export environment variables every
session. Holds the intervals.icu credentials, the vault path, and (optionally) the current
training block.

Precedence, per value: explicit CLI argument > environment variable > config file. Secrets
stay overridable from the environment (handy for a one-off run or CI); the file just fills
in what the environment doesn't provide.

The config file is the athlete's private data — it carries the API key in plaintext — so it
lives in the home directory, never the repo, and should be locked down (chmod 600). Format
is TOML (parsed by the stdlib `tomllib`, Python 3.11+) or JSON (any Python 3), chosen by the
file extension; either way there is no third-party dependency, so the skill still installs
cold.

Search order when no path is given:
  $THRESHOLD_CONFIG
  ~/.config/threshold/config.toml
  ~/.config/threshold/config.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ingest.intervals_icu import Credentials, IntervalsError

_DEFAULT_PATHS = (
    "~/.config/threshold/config.toml",
    "~/.config/threshold/config.json",
)


def _candidate_paths(path: str | None) -> list[str]:
    if path:
        return [path]
    env = os.getenv("THRESHOLD_CONFIG")
    return [env] if env else list(_DEFAULT_PATHS)


def _find_config(path: str | None = None) -> Path | None:
    for candidate in _candidate_paths(path):
        p = Path(candidate).expanduser()
        if p.is_file():
            return p
    return None


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text) or {}
    try:
        import tomllib
    except ModuleNotFoundError as exc:  # Python < 3.11 has no stdlib TOML
        raise IntervalsError(
            f"reading {path} needs Python 3.11+ for TOML; use a .json config instead"
        ) from exc
    return tomllib.loads(text) or {}


def load_config(path: str | None = None) -> dict:
    """Return the config mapping, or {} when there is no config file. An explicit `path`
    that doesn't exist is an error (a likely typo); a missing default file is not. Raises
    IntervalsError on a malformed or unreadable file — a clear failure beats a silently
    empty config."""
    found = _find_config(path)
    if not found:
        if path:
            raise IntervalsError(f"config file not found: {path}")
        return {}
    try:
        data = _parse(found)
    except (ValueError, OSError) as exc:
        raise IntervalsError(f"could not read config {found}: {exc}") from exc
    if not isinstance(data, dict):
        raise IntervalsError(f"config {found} must have a table/object at the top level")
    return data


def resolve_credentials(config: dict) -> Credentials:
    """intervals.icu credentials, environment first then the config file. Raises
    IntervalsError naming what's missing rather than failing deep in an HTTP call."""
    athlete_id = os.getenv("INTERVALS_ATHLETE_ID") or config.get("athlete_id")
    api_key = os.getenv("INTERVALS_API_KEY") or config.get("api_key")
    missing = [n for n, v in (("athlete_id", athlete_id), ("api_key", api_key)) if not v]
    if missing:
        raise IntervalsError(
            "missing credential(s): " + ", ".join(missing) + " — set them in the config "
            "file or as INTERVALS_ATHLETE_ID / INTERVALS_API_KEY"
        )
    return Credentials(athlete_id=str(athlete_id), api_key=str(api_key))

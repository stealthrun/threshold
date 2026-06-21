"""Tests for the optional on-disk config (config.py).

Cover the loader (TOML + JSON, missing/malformed files) and the credential precedence
(environment over file). No network; env is manipulated through monkeypatch and the default
search paths are redirected to a temp dir so a real ~/.config/threshold never interferes.
"""

import pytest

import config
from ingest.intervals_icu import IntervalsError

ENV_VARS = ("THRESHOLD_CONFIG", "INTERVALS_ATHLETE_ID", "INTERVALS_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """Start each test with no relevant env vars and the default search paths pointed at an
    empty temp dir, so results don't depend on the machine running them."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "_DEFAULT_PATHS", (str(tmp_path / "absent.toml"),))


# ── loading ──────────────────────────────────────────────────────────────────────────────

def test_no_config_is_empty_dict():
    assert config.load_config() == {}


def test_loads_toml(tmp_path):
    pytest.importorskip("tomllib")  # TOML parsing needs Python 3.11+; JSON is the fallback
    p = tmp_path / "c.toml"
    p.write_text('athlete_id = "i9"\napi_key = "k"\nvault = "~/v"\n', encoding="utf-8")
    cfg = config.load_config(str(p))
    assert cfg["athlete_id"] == "i9" and cfg["vault"] == "~/v"


def test_loads_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"athlete_id": "i9", "api_key": "k"}', encoding="utf-8")
    assert config.load_config(str(p))["athlete_id"] == "i9"


def test_loads_nested_block_table(tmp_path):
    pytest.importorskip("tomllib")
    p = tmp_path / "c.toml"
    p.write_text('athlete_id = "i9"\n[block]\nname = "base"\nweek = 6\n', encoding="utf-8")
    assert config.load_config(str(p))["block"] == {"name": "base", "week": 6}


def test_env_var_points_at_config(tmp_path, monkeypatch):
    pytest.importorskip("tomllib")
    p = tmp_path / "c.toml"
    p.write_text('athlete_id = "fromenvpath"\n', encoding="utf-8")
    monkeypatch.setenv("THRESHOLD_CONFIG", str(p))
    assert config.load_config()["athlete_id"] == "fromenvpath"


def test_explicit_missing_path_raises(tmp_path):
    with pytest.raises(IntervalsError, match="not found"):
        config.load_config(str(tmp_path / "missing.toml"))


def test_malformed_file_raises(tmp_path):
    pytest.importorskip("tomllib")
    p = tmp_path / "c.toml"
    p.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(IntervalsError):
        config.load_config(str(p))


# ── credential precedence ────────────────────────────────────────────────────────────────

def test_credentials_from_config():
    creds = config.resolve_credentials({"athlete_id": "i9", "api_key": "k"})
    assert creds.athlete_id == "i9" and creds.api_key == "k"


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "fromenv")
    monkeypatch.setenv("INTERVALS_API_KEY", "envkey")
    creds = config.resolve_credentials({"athlete_id": "fromfile", "api_key": "filekey"})
    assert creds.athlete_id == "fromenv" and creds.api_key == "envkey"


def test_partial_env_falls_back_to_config(monkeypatch):
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "fromenv")        # only id in env
    creds = config.resolve_credentials({"athlete_id": "x", "api_key": "filekey"})
    assert creds.athlete_id == "fromenv" and creds.api_key == "filekey"


def test_missing_credentials_raises():
    with pytest.raises(IntervalsError, match="missing credential"):
        config.resolve_credentials({})

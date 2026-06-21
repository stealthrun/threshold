"""Tests for the intervals.icu ingestion layer.

No network: the HTTP seam is stubbed, and the mapping/aggregation logic is pinned with
fixtures. What's verified is that an intervals.icu activity becomes a valid `session` dict
the core can read, and that the credentials/error seams behave.
"""

import base64
from datetime import date

import pytest

from derive_signals import derive_signals
from ingest import intervals_icu as icu

# A representative intervals.icu activity object (documented field names).
RAW_VO2 = {
    "id": "i111", "start_date_local": "2026-06-15T07:30:00", "type": "Run",
    "name": "6x800m", "distance": 9500, "moving_time": 2185,
    "average_heartrate": 170, "max_heartrate": 178,
    "icu_hr_zone_times": [120, 300, 400, 600, 765],  # Z1..Z5 seconds
}
RAW_EASY = {
    "id": "i112", "start_date_local": "2026-06-16T18:00:00", "type": "Run",
    "name": "easy", "distance": 10000, "moving_time": 3000,
    "average_heartrate": 142, "max_heartrate": 150,
    "icu_hr_zone_times": [1500, 1500, 0, 0, 0],  # all easy
}
RAW_RIDE = {"id": "i113", "start_date_local": "2026-06-16T12:00:00", "type": "Ride",
            "distance": 40000, "moving_time": 4800}


# ── credentials seam ──────────────────────────────────────────────────────────────────

def test_credentials_from_env(monkeypatch):
    monkeypatch.setenv("INTERVALS_ATHLETE_ID", "i999")
    monkeypatch.setenv("INTERVALS_API_KEY", "secret-key")
    creds = icu.Credentials.from_env()
    assert creds.athlete_id == "i999"


def test_credentials_missing_var_names_it(monkeypatch):
    monkeypatch.delenv("INTERVALS_ATHLETE_ID", raising=False)
    monkeypatch.setenv("INTERVALS_API_KEY", "k")
    with pytest.raises(icu.IntervalsError, match="INTERVALS_ATHLETE_ID"):
        icu.Credentials.from_env()


def test_auth_header_is_basic_api_key():
    creds = icu.Credentials("i1", "thekey")
    expected = "Basic " + base64.b64encode(b"API_KEY:thekey").decode()
    assert creds._auth_header() == expected


# ── zone distribution + classification ────────────────────────────────────────────────

def test_zone_dist_normalises_to_fractions():
    z = icu._zone_dist([100, 100, 0, 0, 300])
    assert z == {"Z1": 0.2, "Z2": 0.2, "Z5": 0.6}


def test_zone_dist_empty_when_no_data():
    assert icu._zone_dist(None) == {}
    assert icu._zone_dist([0, 0, 0]) == {}


def test_classify_by_dominant_intensity():
    assert icu._classify_run({"Z5": 0.4, "Z4": 0.2}, 9.5) == "vo2"
    assert icu._classify_run({"Z4": 0.3, "Z3": 0.2}, 12) == "threshold"
    assert icu._classify_run({"Z3": 0.5}, 10) == "tempo"
    assert icu._classify_run({"Z2": 0.9}, 30) == "long"      # far + easy
    assert icu._classify_run({"Z2": 0.9}, 8) == "easy"


# ── activity → session mapping ────────────────────────────────────────────────────────

def test_activity_to_session_maps_core_fields():
    s = icu.activity_to_session(RAW_VO2)
    assert s["source_id"] == "i111"
    assert s["date"] == "2026-06-15"
    assert s["activity_type"] == "vo2"
    assert s["distance_km"] == 9.5
    assert s["avg_pace_sec_per_km"] == round(2185 / 9500 * 1000)  # 230
    assert s["avg_hr"] == 170 and s["max_hr"] == 178
    assert s["zone_dist"]["Z5"] > 0
    assert s["feedback"] == {}  # subjective input is the athlete's, not the API's


def test_mapped_session_is_a_valid_core_input():
    # the real contract: derive_signals must run on the mapped dict without error
    s = icu.activity_to_session(RAW_VO2)
    sig = derive_signals(s)
    assert sig["key_signal"]  # produced something


def test_activity_to_session_carries_plan_targets_through():
    s = icu.activity_to_session(RAW_VO2, plan_targets={"work_rep_count": 6})
    assert s["plan_targets"] == {"work_rep_count": 6}


def test_activity_to_session_tolerates_missing_fields():
    s = icu.activity_to_session({"id": "x", "type": "Run"})
    assert s["distance_km"] is None
    assert s["avg_pace_sec_per_km"] is None
    assert s["zone_dist"] == {}


# ── week summaries ────────────────────────────────────────────────────────────────────

def test_summarise_weeks_buckets_by_iso_week():
    today = date(2026, 6, 17)  # a Wednesday
    sessions = [
        {"date": "2026-06-15", "distance_km": 9.5},   # this week
        {"date": "2026-06-16", "distance_km": 10.0},  # this week
        {"date": "2026-06-09", "distance_km": 12.0},  # week -1
    ]
    weeks = icu.summarise_weeks(sessions, weeks=4, today=today)
    assert weeks[0] == {"label": "this week", "volume_km": 19.5, "sessions": 2}
    assert weeks[1] == {"label": "week -1", "volume_km": 12.0, "sessions": 1}
    assert weeks[2]["sessions"] == 0


def test_summarise_weeks_ignores_bad_dates():
    weeks = icu.summarise_weeks([{"date": "", "distance_km": 5}], weeks=2,
                                today=date(2026, 6, 17))
    assert weeks[0]["sessions"] == 0


# ── fetch_recent (HTTP stubbed) ───────────────────────────────────────────────────────

def test_fetch_recent_maps_runs_only_and_sorts(monkeypatch):
    monkeypatch.setattr(icu, "fetch_activities", lambda *a, **k: [RAW_EASY, RAW_RIDE, RAW_VO2])
    sessions, recent = icu.fetch_recent(icu.Credentials("i1", "k"), weeks=4,
                                        today=date(2026, 6, 17))
    assert [s["source_id"] for s in sessions] == ["i112", "i111"]  # ride dropped, newest first
    assert sum(w["sessions"] for w in recent) == 2


# ── HTTP error surface ────────────────────────────────────────────────────────────────

def test_get_raises_intervals_error_on_http(monkeypatch):
    import urllib.error

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(icu.urllib.request, "urlopen", boom)
    with pytest.raises(icu.IntervalsError, match="401"):
        icu._get("/x", {}, icu.Credentials("i1", "k"))

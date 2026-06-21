"""Tests for intervals.icu lap ingestion + the derived metrics.

The lap fixture mirrors the real /activity/{id}/intervals shape (icu_intervals with
type / distance / moving_time / average_heartrate / average_speed / zone). No network:
the fetch is stubbed, the mapping and metric math are pinned, and the real contract —
that mapped laps + metrics flow into derive_signals — is asserted.
"""

from datetime import date

from derive_signals import derive_signals
from ingest import intervals_icu as icu
from ingest import metrics

# Trimmed to the real field names, shaped like a 4-rep workout: warmup, 4x ~1km work,
# recovery floats between. average_speed is m/s.
RAW_INTERVALS = {
    "id": "i159126333",
    "icu_intervals": [
        {"type": "WARMUP", "distance": 1000, "moving_time": 300,
         "average_heartrate": 130, "max_heartrate": 144, "average_speed": 3.33, "zone": 1},
        {"type": "WORK", "distance": 1000, "moving_time": 200,
         "average_heartrate": 168, "max_heartrate": 175, "average_speed": 5.0, "zone": 5},
        {"type": "RECOVERY", "distance": 200, "moving_time": 90,
         "average_heartrate": 140, "max_heartrate": 150, "average_speed": 2.2, "zone": 1},
        {"type": "WORK", "distance": 1000, "moving_time": 205,
         "average_heartrate": 172, "max_heartrate": 178, "average_speed": 4.88, "zone": 5},
        {"type": "RECOVERY", "distance": 200, "moving_time": 90,
         "average_heartrate": 142, "max_heartrate": 150, "average_speed": 2.2, "zone": 1},
        {"type": "WORK", "distance": 1000, "moving_time": 210,
         "average_heartrate": 175, "max_heartrate": 179, "average_speed": 4.76, "zone": 5},
    ],
}


# ── lap mapping ───────────────────────────────────────────────────────────────────────

def test_interval_to_lap_maps_real_fields():
    lap = icu.interval_to_lap(RAW_INTERVALS["icu_intervals"][1])
    assert lap["lap_type"] == "work"
    assert lap["distance_m"] == 1000
    assert lap["duration_sec"] == 200
    assert lap["avg_hr"] == 168 and lap["max_hr"] == 175
    assert lap["avg_pace_sec_per_km"] == 200       # 1000 / 5.0 m/s


def test_intervals_to_laps_preserves_type_and_order():
    laps = icu.intervals_to_laps(RAW_INTERVALS)
    assert [l["lap_type"] for l in laps] == \
        ["warmup", "work", "recovery", "work", "recovery", "work"]


def test_attach_laps_sets_work_laps_derive_signals_can_read(monkeypatch):
    monkeypatch.setattr(icu, "fetch_activity_intervals", lambda *a, **k: RAW_INTERVALS)
    session = {"source_id": "i159126333", "activity_type": "vo2"}
    icu.attach_laps(icu.Credentials("i1", "k"), session)
    work = [l for l in session["laps"] if l["lap_type"] == "work"]
    assert len(work) == 3                            # warmup + recoveries excluded


def test_pace_from_speed():
    assert icu._pace_from_speed(5.0) == 200
    assert icu._pace_from_speed(None) is None


# ── pacing consistency ────────────────────────────────────────────────────────────────

def test_pacing_consistency_excludes_recovery():
    laps = icu.intervals_to_laps(RAW_INTERVALS)
    pc = metrics.pacing_consistency(laps)
    # three tight work paces (~200-210) + a 300 warmup; recoveries (slow) excluded
    assert pc is not None and 0.7 < pc < 1.0


def test_pacing_consistency_none_with_one_lap():
    assert metrics.pacing_consistency([{"avg_pace_sec_per_km": 200, "lap_type": "work"}]) is None


# ── decoupling ────────────────────────────────────────────────────────────────────────

def _steady_laps(pace_first, pace_second, hr_first, hr_second, n=6):
    half = n // 2
    return (
        [{"lap_type": "work", "duration_sec": 600, "avg_hr": hr_first,
          "avg_pace_sec_per_km": pace_first} for _ in range(half)] +
        [{"lap_type": "work", "duration_sec": 600, "avg_hr": hr_second,
          "avg_pace_sec_per_km": pace_second} for _ in range(half)]
    )


def test_decoupling_detects_drift_on_long_steady():
    # second half slower for the same HR -> efficiency drifted -> positive decoupling
    laps = _steady_laps(300, 318, 150, 150)
    pct, valid = metrics.decoupling(laps, duration_sec=3600, zone_dist={"Z2": 1.0})
    assert valid and pct > 5


def test_decoupling_invalid_when_too_short():
    laps = _steady_laps(300, 300, 150, 150)
    assert metrics.decoupling(laps, duration_sec=1800, zone_dist={"Z2": 1.0}) == (None, False)


def test_decoupling_invalid_on_interval_intensity():
    laps = _steady_laps(220, 230, 165, 170)
    assert metrics.decoupling(laps, duration_sec=3600, zone_dist={"Z5": 0.4}) == (None, False)


# ── enrich_session + the real contract ────────────────────────────────────────────────

def test_enrich_session_folds_metrics_in():
    session = {"laps": icu.intervals_to_laps(RAW_INTERVALS), "duration_sec": 1095,
               "zone_dist": {"Z5": 0.5}}
    metrics.enrich_session(session)
    assert "pacing_consistency" in session
    assert session["decoupling_valid"] is False     # interval intensity

def test_enrich_session_noop_without_laps():
    assert metrics.enrich_session({"laps": []}) == {"laps": []}


def test_metrics_reach_derive_signals():
    # a long run that drifted: enrich -> decoupling -> derive_signals downgrades stimulus
    laps = _steady_laps(300, 340, 150, 152, n=6)
    session = {"activity_type": "long", "zone_dist": {"Z2": 1.0}, "duration_sec": 3600,
               "laps": laps}
    metrics.enrich_session(session)
    assert session["decoupling_valid"] is True
    # derive_signals reads decoupling_pct/valid; a big drift downgrades the stimulus
    assert derive_signals(session)["stimulus_quality"] in ("partial", "failed")

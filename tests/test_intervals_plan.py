"""Tests for intervals.icu plan ingestion.

No network: the workout_doc parse and plan-matching logic are pinned with fixtures built
from the verified intervals.icu event shape (see the lab's fetch_plan.py). The real
contract — that the produced plan_targets drive derive_vs_plan — is asserted too.
"""

from datetime import date

import pytest

from derive_signals import derive_vs_plan
from ingest import intervals_plan as plan

# A structured interval workout: warmup, 6x800m @ 3:05/km with 2:00 float, cooldown.
EVENT_INTERVALS = {
    "start_date_local": "2026-06-15T07:30:00", "name": "6x800m",
    "workout_doc": {
        "steps": [
            {"warmup": True, "duration": 900, "pace": {"units": "secs/km", "value": 300}},
            {"reps": 6, "steps": [
                {"distance": 800, "pace": {"units": "secs/km", "value": 185}},  # work
                {"duration": 120, "pace": {"units": "secs/km", "value": 360}},  # float
            ]},
            {"cooldown": True, "duration": 600, "pace": {"units": "secs/km", "value": 300}},
        ],
    },
}
# A continuous run with only an event-level distance, no structured doc.
EVENT_CONTINUOUS = {
    "start_date_local": "2026-06-16T18:00:00", "name": "easy 10k",
    "distance": 10000, "workout_doc": {},
}


# ── step pace parsing ─────────────────────────────────────────────────────────────────

def test_step_pace_value_and_range():
    assert plan._step_pace_secs_km({"pace": {"units": "secs/km", "value": 185}}) == 185
    assert plan._step_pace_secs_km({"pace": {"units": "secs/km", "start": 180, "end": 190}}) == 185


def test_step_pace_none_when_not_secs_km():
    assert plan._step_pace_secs_km({"pace": {"units": "%pace", "value": 105}}) is None
    assert plan._step_pace_secs_km({}) is None


# ── work-segment detection ────────────────────────────────────────────────────────────

def test_work_segments_drops_recovery_and_bookends():
    inner = EVENT_INTERVALS["workout_doc"]["steps"][1]["steps"]
    work = plan._work_segments(inner)
    assert len(work) == 1                       # the 800m, not the slow float
    assert work[0]["distance"] == 800


def test_work_segments_falls_back_to_distance_when_unpaced():
    steps = [{"warmup": True, "duration": 600},
             {"distance": 2000}, {"distance": 2000}]
    assert len(plan._work_segments(steps)) == 2


# ── doc → targets ─────────────────────────────────────────────────────────────────────

def test_targets_from_doc_reps_distance_and_pace():
    t = plan._targets_from_doc(EVENT_INTERVALS["workout_doc"])
    assert t["work_rep_count"] == 6
    assert t["work_distance_m"] == 4800        # 800 * 6
    assert t["work_pace_target_sec_km"] == 185


def test_event_to_plan_targets_continuous_fallback():
    t = plan.event_to_plan_targets(EVENT_CONTINUOUS)
    assert t["work_distance_m"] == 10000
    assert t["name"] == "easy 10k"
    assert "work_pace_target_sec_km" not in t  # none prescribed


def test_event_to_plan_targets_none_when_empty():
    assert plan.event_to_plan_targets({"name": "rest", "workout_doc": {}}) is None


# ── matching to dates ─────────────────────────────────────────────────────────────────

def test_plan_targets_by_date_picks_largest_on_multi_event_day(monkeypatch):
    same_day = [
        {"start_date_local": "2026-06-15T07:00:00", "distance": 3000, "workout_doc": {}},
        {"start_date_local": "2026-06-15T17:00:00", "distance": 12000, "workout_doc": {}},
    ]
    monkeypatch.setattr(plan, "fetch_events", lambda *a, **k: same_day)
    by_date = plan.plan_targets_by_date(plan.Credentials("i1", "k"), "2026-06-15", "2026-06-15")
    assert by_date["2026-06-15"]["work_distance_m"] == 12000  # the main session


def test_attach_plans_sets_and_never_overwrites():
    sessions = [
        {"date": "2026-06-15", "activity_type": "vo2"},                       # gets a plan
        {"date": "2026-06-16", "activity_type": "easy", "plan_targets": {"x": 1}},  # kept
        {"date": "2026-06-17", "activity_type": "easy"},                      # no plan that day
    ]
    plans = {"2026-06-15": {"work_rep_count": 6}, "2026-06-16": {"work_rep_count": 4}}
    plan.attach_plans(sessions, plans)
    assert sessions[0]["plan_targets"] == {"work_rep_count": 6}
    assert sessions[1]["plan_targets"] == {"x": 1}     # not overwritten
    assert "plan_targets" not in sessions[2] or sessions[2].get("plan_targets") is None


# ── the real contract: targets drive vs_plan ──────────────────────────────────────────

def test_produced_targets_drive_vs_plan():
    # an interval session with no laps + a plan target pace it missed -> under
    targets = plan._targets_from_doc(EVENT_INTERVALS["workout_doc"])
    session = {"activity_type": "vo2", "avg_pace_sec_per_km": 205, "plan_targets": targets}
    assert derive_vs_plan(session) == "under"


# ── combined fetch (HTTP stubbed) ─────────────────────────────────────────────────────

def test_fetch_recent_with_plan_attaches(monkeypatch):
    sessions = [{"date": "2026-06-15", "activity_type": "vo2", "distance_km": 9.5}]
    monkeypatch.setattr("ingest.intervals_icu.fetch_recent",
                        lambda *a, **k: (sessions, [{"label": "this week"}]))
    monkeypatch.setattr(plan, "plan_targets_by_date",
                        lambda *a, **k: {"2026-06-15": {"work_rep_count": 6}})
    out, recent = plan.fetch_recent_with_plan(plan.Credentials("i1", "k"),
                                              weeks=4, today=date(2026, 6, 17))
    assert out[0]["plan_targets"] == {"work_rep_count": 6}

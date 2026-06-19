"""Unit tests for the deterministic signal engine.

These test the *rules*, with controlled inputs — not the hand-authored golden labels
(the goldens are target scenarios for the LLM read; some of their signal values are
editorial). Faithfulness to the lab's logic is what's pinned here.
"""

from derive_signals import (
    derive_key_signal,
    derive_stimulus_quality,
    derive_vs_plan,
)


def work(paces, hrs, dist_m=1000):
    """Per-rep work laps in the shape derive_signals reads."""
    return [
        {"lap_type": "work", "distance_m": dist_m, "duration_sec": round(p * dist_m / 1000),
         "avg_hr": h, "avg_pace_sec_per_km": p}
        for p, h in zip(paces, hrs)
    ]


# ── stimulus_quality ──────────────────────────────────────────────────────────────────

def test_sq_breath_above_ceiling_is_partial():
    # easy ceiling is 4; breathing at 6 means it cost more than easy should
    s = {"activity_type": "easy", "zone_dist": {"Z2": 1.0},
         "feedback": {"rpe_breath": 6}}
    assert derive_stimulus_quality(s) == "partial"


def test_sq_breath_at_ceiling_is_complete():
    # ceiling is the highest *still-normal* value — at the ceiling is fine
    s = {"activity_type": "threshold", "zone_dist": {"Z4": 1.0},
         "feedback": {"rpe_breath": 7}}
    assert derive_stimulus_quality(s) == "complete"


def test_sq_vo2_high_breath_still_complete():
    # vo2's ceiling is effectively off — maximal breathing is expected
    s = {"activity_type": "vo2", "zone_dist": {"Z5": 1.0},
         "feedback": {"rpe_breath": 9}}
    assert derive_stimulus_quality(s) == "complete"


def test_sq_pacing_collapse_is_failed():
    s = {"activity_type": "easy", "zone_dist": {"Z2": 1.0},
         "pacing_consistency": 0.65}
    assert derive_stimulus_quality(s) == "failed"


def test_sq_pacing_degraded_is_partial():
    s = {"activity_type": "easy", "zone_dist": {"Z2": 1.0},
         "pacing_consistency": 0.75}
    assert derive_stimulus_quality(s) == "partial"


def test_sq_extreme_decoupling_is_failed():
    s = {"activity_type": "long", "zone_dist": {"Z2": 1.0},
         "decoupling_valid": True, "decoupling_pct": 18}
    assert derive_stimulus_quality(s) == "failed"


def test_sq_legs_rpe_never_downgrades():
    # legs RPE is carryover fatigue, not a stimulus signal — must be ignored
    s = {"activity_type": "threshold", "zone_dist": {"Z4": 1.0},
         "feedback": {"rpe_breath": 7, "rpe_legs": 10}}
    assert derive_stimulus_quality(s) == "complete"


def test_sq_none_without_type_or_zones():
    assert derive_stimulus_quality({"activity_type": "mixed", "zone_dist": {"Z2": 1.0}}) is None
    assert derive_stimulus_quality({"activity_type": "easy", "zone_dist": {}}) is None


# ── vs_plan ───────────────────────────────────────────────────────────────────────────

def test_vs_plan_unplanned_without_plan():
    assert derive_vs_plan({"activity_type": "easy"}) == "unplanned"


def test_vs_plan_interval_reps_cut_is_under():
    s = {"activity_type": "vo2", "laps": work([186, 185, 187], [171, 174, 176], 800),
         "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185}}
    assert derive_vs_plan(s) == "under"


def test_vs_plan_interval_reps_exceeded_is_over():
    s = {"activity_type": "threshold", "laps": work([238] * 5, [162] * 5, 2000),
         "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240}}
    assert derive_vs_plan(s) == "over"


def test_vs_plan_interval_reps_met_pace_slow_is_under():
    s = {"activity_type": "threshold", "laps": work([248, 250, 252, 255], [162, 164, 165, 166], 2000),
         "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240}}
    assert derive_vs_plan(s) == "under"


def test_vs_plan_interval_reps_met_pace_on_is_on_target():
    s = {"activity_type": "threshold", "laps": work([238, 239, 238, 240], [160, 163, 164, 166], 2000),
         "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240}}
    assert derive_vs_plan(s) == "on_target"


def test_vs_plan_continuous_pace_on_target():
    # tempo with warmup/cooldown and no laps — judged on average pace vs target
    s = {"activity_type": "tempo", "avg_pace_sec_per_km": 245,
         "plan_targets": {"work_distance_m": 6000, "work_pace_target_sec_km": 245}}
    assert derive_vs_plan(s) == "on_target"


def test_vs_plan_continuous_distance_under():
    s = {"activity_type": "long", "distance_km": 20.0,
         "plan_targets": {"work_distance_m": 26000}}
    assert derive_vs_plan(s) == "under"


# ── key_signal ────────────────────────────────────────────────────────────────────────

def test_key_signal_cut_on_achilles():
    s = {"activity_type": "vo2", "laps": work([186, 185, 187], [171, 174, 176], 800),
         "feedback": {"achilles_flag": True, "rpe_breath": 6},
         "plan_targets": {"work_rep_count": 6}}
    assert derive_key_signal(s) == "Cut to 3 of 6 reps when the Achilles flared."


def test_key_signal_vo2_fade_below_max():
    s = {"activity_type": "vo2",
         "laps": work([184, 187, 192, 199, 205, 205], [172, 175, 176, 177, 177, 178], 800),
         "feedback": {"rpe_breath": 7},
         "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185}}
    assert derive_key_signal(s) == "Pace faded across the reps while heart rate stayed below max."


def test_key_signal_aerobic_drift():
    s = {"activity_type": "easy", "zone_dist": {"Z1": 0.15, "Z2": 0.4, "Z3": 0.45},
         "feedback": {"rpe_breath": 6}}
    assert derive_key_signal(s) == "An easy-day run that drifted above easy."


def test_key_signal_felt_smooth_high_cost():
    s = {"activity_type": "tempo", "avg_pace_sec_per_km": 245, "flags": ["hr_drift"],
         "feedback": {"rpe_breath": 5},
         "plan_targets": {"work_distance_m": 6000, "work_pace_target_sec_km": 245}}
    assert derive_key_signal(s) == "Felt smooth, but the heart worked harder than the pace usually costs."


def test_key_signal_clean_interval():
    s = {"activity_type": "threshold", "zone_dist": {"Z4": 1.0},
         "laps": work([238, 239, 238, 240], [160, 163, 164, 166], 2000),
         "feedback": {"rpe_breath": 7},
         "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240}}
    assert derive_key_signal(s) == "Held target across all 4 reps."

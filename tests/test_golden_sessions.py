"""Tests for the golden fixtures.

PR A's whole value is that the goldens are honest *before* any model runs: each scenario
must actually derive the signal it claims to isolate, and each must carry a real rubric.
These assertions are deterministic — no `claude` process is spawned.
"""

import pytest

from derive_signals import derive_signals
from evals.golden_sessions import GOLDENS, GOLDENS_BY_NAME, load_golden

# The key_signal each scenario is built to isolate. If a fixture edit breaks one of these,
# the golden no longer tests what it says it does — which is exactly what we want to catch.
EXPECTED_KEY_SIGNAL = {
    "clean_threshold": "Held target across all 4 reps.",
    "faded_vo2": "Pace faded across the reps while heart rate stayed below max.",
    "easy_drifted_tempo": "An easy-day run that drifted above easy.",
    "achilles_flare": "Cut to 3 of 6 reps when the Achilles flared.",
    "masking_week": "Held target across all 4 reps.",
    "felt_smooth_high_cost": "Felt smooth, but the heart worked harder than the pace usually costs.",
    "long_run_on_plan": "Controlled aerobic long run, on plan.",
    "threshold_under_target": "Came in under the target pace.",
}

EXPECTED_VS_PLAN = {
    "clean_threshold": "on_target",
    "faded_vo2": "under",
    "easy_drifted_tempo": "unplanned",
    "achilles_flare": "under",
    "masking_week": "on_target",
    "felt_smooth_high_cost": "on_target",
    "long_run_on_plan": "on_target",
    "threshold_under_target": "under",
}


def test_all_eight_goldens_present_and_named_uniquely():
    names = [g["name"] for g in GOLDENS]
    assert len(GOLDENS) == 8
    assert len(set(names)) == 8
    assert set(names) == set(EXPECTED_KEY_SIGNAL)


@pytest.mark.parametrize("name", list(EXPECTED_KEY_SIGNAL))
def test_golden_derives_the_signal_it_isolates(name):
    sig = derive_signals(load_golden(name)["session"])
    assert sig["key_signal"] == EXPECTED_KEY_SIGNAL[name]
    assert sig["vs_plan"] == EXPECTED_VS_PLAN[name]


@pytest.mark.parametrize("g", GOLDENS, ids=[g["name"] for g in GOLDENS])
def test_golden_carries_a_real_rubric(g):
    assert g["isolates"].strip()
    assert g["must_address"] and all(isinstance(x, str) and x.strip() for x in g["must_address"])
    assert g["must_not"] and all(isinstance(x, str) and x.strip() for x in g["must_not"])


@pytest.mark.parametrize("g", GOLDENS, ids=[g["name"] for g in GOLDENS])
def test_golden_session_is_a_valid_engine_input(g):
    # the session must carry the minimum derive_signals needs to classify it
    s = g["session"]
    assert s.get("activity_type")
    assert derive_signals(s)["key_signal"]  # derivation runs without error


def test_clean_threshold_is_the_control():
    # the control must be a genuinely clean session, or it can't catch manufactured concern
    g = GOLDENS_BY_NAME["clean_threshold"]
    sig = derive_signals(g["session"])
    assert sig["stimulus_quality"] == "complete"
    assert sig["vs_plan"] == "on_target"
    assert not g["session"]["feedback"]["achilles_flag"]

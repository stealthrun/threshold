"""Unit tests for the interpretation step.

These pin the deterministic half of interpret.py — that the prompt is assembled from all
four sources in one place, and that the voice-guard retry fires exactly once on a leak.
The model call itself is stubbed; no `claude` process is spawned here.
"""

import interpret
from coach_voice import VOICE_GUARDRAILS

SESSION = {
    "activity_type": "vo2",
    "distance_km": 9.5, "avg_pace_sec_per_km": 230, "avg_hr": 170, "max_hr": 178,
    "zone_dist": {"Z2": 0.1, "Z3": 0.2, "Z4": 0.3, "Z5": 0.4},
    "flags": ["pace_fade"],
    "laps": [
        {"lap_type": "work", "distance_m": 800, "duration_sec": p * 800 // 1000,
         "avg_hr": h, "avg_pace_sec_per_km": p}
        for p, h in zip([184, 187, 192, 199, 205, 205], [172, 175, 176, 177, 177, 178])
    ],
    "feedback": {"rpe_breath": 7, "rpe_legs": 9, "achilles_flag": False,
                 "feel": "legs cooked by rep 4"},
    "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
}
RECENT = [{"label": "this week", "volume_km": 78, "sessions": 6,
           "read": "Top of your tolerance, legs heavy midweek."}]


# ── prompt assembly: one place, all four sources ──────────────────────────────────────

def test_prompt_includes_the_voice_contract():
    assert VOICE_GUARDRAILS in interpret.build_prompt(SESSION, RECENT)


def test_prompt_includes_the_coaching_framework():
    prompt = interpret.build_prompt(SESSION, RECENT)
    # the framework's defining trait must reach the model, read from the reference file
    assert "speed-dominant" in prompt
    assert "COACHING FRAMEWORK:" in prompt


def test_prompt_includes_the_derived_signals():
    # the model interprets the deterministic signals; they must be in the prompt verbatim
    prompt = interpret.build_prompt(SESSION, RECENT)
    assert "Pace faded across the reps while heart rate stayed below max." in prompt
    assert "stimulus_quality: complete" in prompt   # breath stayed within the VO2 ceiling
    assert "vs_plan: under" in prompt               # the fade put work pace under target


def test_prompt_includes_session_facts_and_plan_target():
    prompt = interpret.build_prompt(SESSION, RECENT)
    assert "6 reps planned" in prompt
    assert "target pace 3:05/km" in prompt          # 185 s/km, athlete-facing m:ss
    assert "legs cooked by rep 4" in prompt          # the feel note


def test_prompt_includes_recent_week_context():
    prompt = interpret.build_prompt(SESSION, RECENT)
    assert "this week: 78km, 6 sessions" in prompt
    assert "Top of your tolerance" in prompt


def test_unplanned_session_renders_without_a_plan_block():
    s = dict(SESSION); s.pop("plan_targets")
    assert "unplanned session" in interpret.build_prompt(s, RECENT)


# ── block context ─────────────────────────────────────────────────────────────────────

BLOCK = {"name": "competition", "phase": "taper", "week": 2, "total_weeks": 2,
         "focus": "shedding fatigue for the goal race"}


def test_prompt_includes_block_context():
    prompt = interpret.build_prompt(SESSION, RECENT, BLOCK)
    assert "BLOCK (where this sits in the plan):" in prompt
    assert "competition, taper phase (week 2 of 2)" in prompt
    assert "shedding fatigue for the goal race" in prompt


def test_prompt_renders_gracefully_without_a_block():
    # block is optional; its absence must not break assembly and must be explicit
    prompt = interpret.build_prompt(SESSION, RECENT)
    assert "BLOCK (where this sits in the plan):" in prompt
    assert "none provided" in prompt


def test_block_with_partial_fields():
    prompt = interpret.build_prompt(SESSION, RECENT, {"name": "base build", "week": 6})
    assert "base build (week 6)" in prompt


def test_same_session_different_block_changes_the_prompt():
    # the whole point of block context: identical session, different prompt to the model
    build = {"name": "base build", "phase": "build", "week": 6, "total_weeks": 8}
    taper = {"name": "competition", "phase": "taper", "week": 2, "total_weeks": 2}
    assert interpret.build_prompt(SESSION, RECENT, build) != \
        interpret.build_prompt(SESSION, RECENT, taper)


# ── formatting helpers ────────────────────────────────────────────────────────────────

def test_fmt_pace():
    assert interpret._fmt_pace(185) == "3:05/km"
    assert interpret._fmt_pace(None) == "n/a"


# ── the voice-guard retry trigger ─────────────────────────────────────────────────────

def test_clean_first_output_is_not_regenerated(monkeypatch):
    calls = []

    def fake_call(prompt, timeout=120):
        calls.append(prompt)
        return "Your legs tapped out before your heart did. Cut to four reps next time."

    monkeypatch.setattr(interpret, "call_claude", fake_call)
    out = interpret.interpret(SESSION, RECENT)
    assert "tapped out" in out
    assert len(calls) == 1  # clean output -> no retry


def test_dirty_first_output_triggers_exactly_one_retry(monkeypatch):
    outputs = iter([
        "You spent 38% in Z5 with clear decoupling.",  # dirty: leaks % / Z5 / decoupling
        "Your legs tapped out before your heart reached its ceiling.",  # clean retry
    ])
    calls = []

    def fake_call(prompt, timeout=120):
        calls.append(prompt)
        return next(outputs)

    monkeypatch.setattr(interpret, "call_claude", fake_call)
    out = interpret.interpret(SESSION, RECENT)
    assert "tapped out" in out
    assert len(calls) == 2                       # one retry, not a loop
    assert "leaked forbidden content" in calls[1]  # correction names the leak
    assert "decoupl" in calls[1]


def test_no_model_returns_none(monkeypatch):
    monkeypatch.setattr(interpret, "call_claude", lambda *a, **k: None)
    assert interpret.interpret(SESSION, RECENT) is None

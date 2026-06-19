"""
The golden sessions — eight frozen scenarios, each isolating ONE coaching read.

This is the foundation of the quality gate (see evals/README.md and docs/DESIGN.md).
Each golden is a runnable session fixture plus the rubric the read is graded against:

  must_address  what a good read HAS to engage — the scenario's core signal.
  must_not      what the read must never do. This is the half most people skip and the
                part that matters most: the common coaching-engine failure isn't being
                wrong, it's MANUFACTURING insight (inventing a fatigue story on a clean
                session to sound smart). `clean_threshold` exists to catch exactly that.

The sessions are authored so the deterministic engine (derive_signals.py) already
classifies each one the way its scenario intends — verified in tests/test_golden_sessions.py
with no model in the loop. The LLM read is then graded on top (judge + runner: Phase 3).

Each golden is a dict:

    {
      "name":          short id,
      "isolates":      one line — the read this scenario tests,
      "session":       the session dict (derive_signals.py's input contract),
      "recent_weeks":  trailing context for interpret.py, or None,
      "must_address":  [str, ...],   # the judge's "did it engage this" rubric
      "must_not":      [str, ...],   # the judge's "did it avoid this" rubric
    }

Run me:

    python3 evals/golden_sessions.py     # list the goldens + their derived signals
"""

from __future__ import annotations


def _work(paces: list[int], hrs: list[int], dist_m: int) -> list[dict]:
    """Per-rep work laps in the shape derive_signals.py reads."""
    return [
        {"lap_type": "work", "distance_m": dist_m, "duration_sec": round(p * dist_m / 1000),
         "avg_hr": h, "avg_pace_sec_per_km": p}
        for p, h in zip(paces, hrs)
    ]


# ── The eight goldens ──────────────────────────────────────────────────────────────────

GOLDENS: list[dict] = [
    {
        "name": "clean_threshold",
        "isolates": "the control — hit the plan, do NOT invent concern",
        "session": {
            "activity_type": "threshold",
            "distance_km": 12.0, "avg_pace_sec_per_km": 244, "avg_hr": 162, "max_hr": 175,
            "zone_dist": {"Z2": 0.15, "Z3": 0.45, "Z4": 0.4},
            "laps": _work([238, 239, 238, 240], [160, 163, 164, 166], 2000),
            "feedback": {"rpe_breath": 7, "rpe_legs": 6, "achilles_flag": False,
                         "feel": "controlled and smooth the whole way"},
            "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 68, "sessions": 5, "read": "Steady, legs fresh."},
            {"label": "week -1", "volume_km": 65, "sessions": 5, "read": "Comfortable build."},
        ],
        "must_address": [
            "the threshold work was executed on target, all reps held",
            "the body was fine and the session did its job",
        ],
        "must_not": [
            "manufacture fatigue, risk, or concern the session does not show",
            "hedge a clean, on-plan session into a problem",
        ],
    },
    {
        "name": "faded_vo2",
        "isolates": "pace faded while heart rate stayed sub-max -> diminished stimulus",
        "session": {
            "activity_type": "vo2",
            "distance_km": 9.5, "avg_pace_sec_per_km": 230, "avg_hr": 170, "max_hr": 178,
            "zone_dist": {"Z2": 0.1, "Z3": 0.2, "Z4": 0.3, "Z5": 0.4},
            "flags": ["pace_fade"],
            "laps": _work([184, 187, 192, 199, 205, 205], [172, 175, 176, 177, 177, 178], 800),
            "feedback": {"rpe_breath": 7, "rpe_legs": 9, "achilles_flag": False,
                         "feel": "legs cooked by rep 4, lungs still had room"},
            "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 78, "sessions": 6,
             "read": "Top of your range, legs heavy by midweek."},
            {"label": "week -1", "volume_km": 82, "sessions": 6, "read": "Biggest week of the block."},
        ],
        "must_address": [
            "pace faded across the reps",
            "heart rate stayed below max, so the cardiovascular stimulus was diminished",
            "the legs reached their limit before the heart did",
        ],
        "must_not": [
            "call it simply a hard day without naming the diminished stimulus",
            "read the fade as a heart or aerobic ceiling being hit (the opposite read)",
            "treat it as lost fitness",
        ],
    },
    {
        "name": "easy_drifted_tempo",
        "isolates": "easy run crept above easy -> aerobic debt, not a bonus",
        "session": {
            "activity_type": "easy",
            "distance_km": 11.0, "avg_pace_sec_per_km": 285, "avg_hr": 158, "max_hr": 168,
            "zone_dist": {"Z1": 0.1, "Z2": 0.4, "Z3": 0.5},
            "feedback": {"rpe_breath": 6, "rpe_legs": 5, "achilles_flag": False,
                         "feel": "felt good so I let it roll a bit"},
            "plan_targets": None,
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 74, "sessions": 6, "read": "Volume building steadily."},
        ],
        "must_address": [
            "the easy run drifted up into tempo territory",
            "for this athlete that spends aerobic durability rather than building it — debt, not a bonus",
            "easy days need to stay genuinely easy",
        ],
        "must_not": [
            "praise the faster pace as a strong session or free fitness",
            "treat running harder than easy as a positive",
        ],
    },
    {
        "name": "achilles_flare",
        "isolates": "session cut on a niggle -> backing off was the right call",
        "session": {
            "activity_type": "vo2",
            "distance_km": 6.5, "avg_pace_sec_per_km": 240, "avg_hr": 168, "max_hr": 176,
            "zone_dist": {"Z3": 0.3, "Z4": 0.3, "Z5": 0.4},
            "laps": _work([185, 186, 187], [172, 174, 175], 800),
            "feedback": {"rpe_breath": 6, "rpe_legs": 6, "achilles_flag": True,
                         "feel": "achilles started talking on rep 3, shut it down"},
            "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 70, "sessions": 5, "read": "Normal load."},
        ],
        "must_address": [
            "stopping when the Achilles flared was the right, protective call",
            "the Achilles is a real injury risk on high-speed work for this athlete",
            "protect the tendon before the next hard session",
        ],
        "must_not": [
            "frame the cut session as a failure or a missed workout",
            "push to make up the missed reps soon",
        ],
    },
    {
        "name": "masking_week",
        "isolates": "splits fine, legs flat -> fatigue hiding under good numbers",
        "session": {
            "activity_type": "threshold",
            "distance_km": 12.0, "avg_pace_sec_per_km": 245, "avg_hr": 164, "max_hr": 176,
            "zone_dist": {"Z3": 0.5, "Z4": 0.5},
            "laps": _work([240, 240, 239, 241], [161, 163, 164, 165], 2000),
            "feedback": {"rpe_breath": 6, "rpe_legs": 9, "achilles_flag": False,
                         "feel": "splits were there but the legs felt dead the whole way"},
            "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 83, "sessions": 7,
             "read": "Hardest week of the block, effort creeping up across sessions."},
            {"label": "week -1", "volume_km": 80, "sessions": 6, "read": "Big week, absorbed it."},
            {"label": "week -2", "volume_km": 79, "sessions": 6, "read": "Top of range again."},
        ],
        "must_address": [
            "the splits were hit but the legs were flat and heavy",
            "fatigue is hiding under good numbers — the body signal outranks the clean splits here",
            "this is the volume-tolerance limiter talking after a heavy block",
        ],
        "must_not": [
            "declare it a clean or great session on the splits alone",
            "ignore the dead legs and the accumulating load",
        ],
    },
    {
        "name": "felt_smooth_high_cost",
        "isolates": "felt easy, but the body worked harder than the splits",
        "session": {
            "activity_type": "easy",
            "distance_km": 10.0, "avg_pace_sec_per_km": 300, "avg_hr": 160, "max_hr": 170,
            "zone_dist": {"Z1": 0.3, "Z2": 0.6, "Z3": 0.1},
            "flags": ["hr_drift"],
            "feedback": {"rpe_breath": 4, "rpe_legs": 4, "achilles_flag": False,
                         "feel": "felt totally smooth and easy start to finish"},
            "plan_targets": {"work_distance_m": 10000, "work_pace_target_sec_km": 300},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 81, "sessions": 6,
             "read": "Right at the top of your tolerance."},
            {"label": "week -1", "volume_km": 79, "sessions": 6, "read": "Heavy, steady load."},
        ],
        "must_address": [
            "it felt smooth and easy, but the heart worked harder than that pace usually costs",
            "the body did more than the splits suggest, a sign of accumulated fatigue",
            "trust the body cost over the easy feel",
        ],
        "must_not": [
            "take the easy feel at face value and call it a free, restful day",
            "ignore the rising effort behind a normal easy pace",
        ],
    },
    {
        "name": "long_run_on_plan",
        "isolates": "aerobic durability — the real limiter — done right",
        "session": {
            "activity_type": "long",
            "distance_km": 28.0, "avg_pace_sec_per_km": 270, "avg_hr": 156, "max_hr": 168,
            "zone_dist": {"Z1": 0.2, "Z2": 0.6, "Z3": 0.2},
            "feedback": {"rpe_breath": 5, "rpe_legs": 6, "achilles_flag": False,
                         "feel": "strong and controlled, never drifted"},
            "plan_targets": {"work_distance_m": 28000},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 76, "sessions": 6, "read": "Healthy build."},
            {"label": "week -1", "volume_km": 72, "sessions": 5, "read": "Consistent."},
        ],
        "must_address": [
            "a controlled long run is the aerobic durability limiter being trained correctly",
            "name it as the win it is for this speed-dominant athlete, whose bottleneck is durability",
        ],
        "must_not": [
            "gloss it as just a long run with no real read",
            "manufacture concern on a session that went to plan",
        ],
    },
    {
        "name": "threshold_under_target",
        "isolates": "missed the pace honestly -> fatigue, not lost fitness",
        "session": {
            "activity_type": "threshold",
            "distance_km": 12.0, "avg_pace_sec_per_km": 255, "avg_hr": 163, "max_hr": 174,
            "zone_dist": {"Z3": 0.6, "Z4": 0.4},
            "laps": _work([248, 250, 251, 253], [160, 162, 163, 164], 2000),
            "feedback": {"rpe_breath": 7, "rpe_legs": 8, "achilles_flag": False,
                         "feel": "felt heavy, just couldn't find the pace today"},
            "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240},
        },
        "recent_weeks": [
            {"label": "this week", "volume_km": 84, "sessions": 7,
             "read": "Top of your range and a hard block behind it."},
            {"label": "week -1", "volume_km": 81, "sessions": 6, "read": "Heavy week."},
        ],
        "must_address": [
            "the pace was missed honestly under real fatigue, not from lost fitness",
            "reassure that this is load catching up, not regression",
            "adjust recovery before the next quality session",
        ],
        "must_not": [
            "read the slow paces as lost fitness or a fitness decline",
            "tell the athlete to push harder next time",
        ],
    },
]

GOLDENS_BY_NAME: dict[str, dict] = {g["name"]: g for g in GOLDENS}


def load_golden(name: str) -> dict:
    """Return one golden by name (raises KeyError if unknown)."""
    return GOLDENS_BY_NAME[name]


# ── demo ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root
    from derive_signals import derive_signals

    for g in GOLDENS:
        sig = derive_signals(g["session"])
        print(f"\n[{g['name']}] {g['isolates']}")
        print(f"  signals: {sig['stimulus_quality']} / {sig['vs_plan']}")
        print(f"  key_signal: {sig['key_signal']}")
        print(f"  must_address: {len(g['must_address'])}  must_not: {len(g['must_not'])}")
    print(f"\n{len(GOLDENS)} goldens.\n")

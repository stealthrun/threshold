"""
The deterministic signals — the part of the coaching read that must NOT be left to a
language model.

Three signals are computed here, in plain Python, from a single session:

  stimulus_quality  complete | partial | failed | None
                    Did the session deliver the stimulus it was for? Judged on
                    breathing RPE vs the type's ceiling, pacing integrity, and aerobic
                    decoupling — never on legs RPE (that's carryover fatigue, handled
                    elsewhere) and never on "it felt hard".

  vs_plan           on_target | under | over | unplanned
                    Execution against intent. Interval sessions reason in reps then
                    pace; continuous sessions in pace (or distance). Deliberately NOT a
                    compliance percentage: "92% of plan" conflates doing the volume with
                    delivering the stimulus.

  key_signal        one short, factual sentence — what happened.
                    The *nuanced* read (why it happened, what it means for this athlete,
                    what to do next) is the language model's job; this is just the fact
                    it reasons from.

Why deterministic? Because these are auditable, testable, and free, and they're the
inputs the model is allowed to interpret but not invent. Keeping the model's job small
is the whole point — see docs/DESIGN.md.

Distilled from the private lab (srlOS: pipeline/stimulus_quality.py, plan_verdict.py,
taxonomy.py). The taxonomy constants are inlined below so this module runs cold, with no
dependencies beyond the standard library.

Expected session shape (the public contract; see examples/ and evals/):

    {
      "activity_type": "vo2",            # jog|easy|long|tempo|threshold|vo2|mixed
      "distance_km": 9.5,
      "avg_pace_sec_per_km": 230,
      "avg_hr": 170, "max_hr": 178,
      "zone_dist": {"Z2": 0.1, "Z4": 0.3, "Z5": 0.4, ...},   # fractions
      "flags": ["pace_fade"],
      "laps": [{"lap_type": "work", "distance_m": 800,
                "duration_sec": 147, "avg_hr": 172,
                "avg_pace_sec_per_km": 184}, ...],
      "feedback": {"rpe_breath": 7, "rpe_legs": 9,
                   "achilles_flag": False, "feel": "legs went early"},
      "plan_targets": {"work_rep_count": 6, "work_distance_m": 4800,
                       "work_pace_target_sec_km": 185} | None,
      # optional precomputed metrics, used if present:
      "pacing_consistency": 0.0-1.0, "decoupling_pct": float, "decoupling_valid": bool,
    }
"""

from __future__ import annotations

import statistics

# ── Taxonomy (inlined from the lab's pipeline/taxonomy.py) ────────────────────────────

MIXED = "mixed"

# Highest breathing (lungs) RPE, Borg CR10, still coherent with each type's intended
# ventilatory intensity. Exceeding it means the session cost more breath than its
# prescribed intensity warrants → stimulus downgraded. vo2 = 10 is effectively no
# ceiling (VO2 work should feel maximal).
RPE_BREATH_CEILING = {"jog": 3, "easy": 4, "long": 5, "tempo": 6, "threshold": 7, "vo2": 10}

# Types where pacing consistency is a meaningful quality signal. Interval work has
# pace variation by design, so it's excluded there.
STEADY_TYPES = frozenset({"jog", "easy", "long", "tempo"})

# Interval-style types: reason about reps and rep pace, not total distance.
INTERVAL_TYPES = frozenset({"vo2", "threshold"})

# Purely aerobic types: a tight intensity envelope. Drifting above it is aerobic debt.
AEROBIC_TYPES = frozenset({"jog", "easy", "long"})

# The HR zones a well-executed session of each type should mostly sit in.
ZONE_TARGETS = {
    "jog": ["Z1", "Z2"], "easy": ["Z1", "Z2"], "long": ["Z1", "Z2", "Z3"],
    "tempo": ["Z3"], "threshold": ["Z4"], "vo2": ["Z5", "Z6"],
}

# Calibrated max HR for the single athlete this engine coaches. Used only to phrase
# key_signal ("heart rate stayed below max"). See references/coaching_framework.md.
ATHLETE_HR_MAX = 192


# ── Field access (tolerant of the lab's and the public dict's field names) ─────────────

def _session_type(s: dict) -> str | None:
    return s.get("activity_type") or s.get("workout_type")


def _zone_dist(s: dict) -> dict:
    return s.get("zone_dist") or s.get("zone_distribution") or {}


def _feedback(s: dict) -> dict:
    return s.get("feedback") or {}


def _plan_targets(s: dict) -> dict | None:
    return s.get("plan_targets") or (s.get("agent_context") or {}).get("plan_targets")


def _breath_rpe(s: dict) -> int | None:
    """Breathing/lungs RPE. Never falls back to overall `rpe` — that would let
    legs/whole-body fatigue contaminate a respiratory-coherence signal."""
    fb = _feedback(s)
    v = fb.get("rpe_lungs")
    if v is None:
        v = fb.get("rpe_breath")
    return v


def _work_laps(s: dict) -> list[dict]:
    return [lap for lap in (s.get("laps") or []) if lap.get("lap_type") == "work"]


def _pace(lap: dict) -> float | None:
    return lap.get("avg_pace_sec_per_km")


def _executed_work_pace(work: list[dict]) -> float | None:
    """Distance-weighted pace across the work laps (total time / total distance)."""
    dur = sum(lap.get("duration_sec") or 0 for lap in work)
    dist = sum(lap.get("distance_m") or 0 for lap in work)
    if dur and dist:
        return dur / dist * 1000
    paces = [_pace(lap) for lap in work if _pace(lap)]
    return statistics.mean(paces) if paces else None


def _executed_work_distance(s: dict) -> float | None:
    work = _work_laps(s)
    if work:
        d = sum(lap.get("distance_m") or 0 for lap in work)
        if d:
            return d
    km = s.get("distance_km")
    return km * 1000 if km else None


def _pacing_consistency(paces: list[float]) -> float | None:
    """1 - coefficient of variation of the lap paces, clamped to [0, 1]. None when
    there aren't enough laps to judge. A clean reimplementation of the lab's metric."""
    paces = [p for p in paces if p]
    if len(paces) < 2:
        return None
    mean = statistics.mean(paces)
    if mean <= 0:
        return None
    cv = statistics.pstdev(paces) / mean
    return round(max(0.0, min(1.0, 1.0 - cv)), 3)


# ── stimulus_quality (faithful port of the lab's derive_stimulus_quality) ─────────────

def derive_stimulus_quality(s: dict) -> str | None:
    wtype = _session_type(s)
    z = _zone_dist(s)
    rpe_lungs = _breath_rpe(s)

    pacing = s.get("pacing_consistency")
    if pacing is None and wtype in STEADY_TYPES:
        non_recovery = [lap for lap in (s.get("laps") or [])
                        if lap.get("lap_type") not in ("recovery", "rest")]
        pacing = _pacing_consistency([_pace(lap) for lap in non_recovery])

    decoupling_pct = s.get("decoupling_pct")
    decoupling_valid = s.get("decoupling_valid", False)

    if not wtype or wtype == MIXED or not z:
        return None

    # failed: pacing collapsed (steady only), or extreme aerobic drift
    if wtype in STEADY_TYPES and pacing is not None and pacing < 0.70:
        return "failed"
    if decoupling_valid and decoupling_pct is not None and decoupling_pct > 15:
        return "failed"

    quality = "complete"

    # partial: breath cost above the type's ceiling (no +1 tolerance — the ceiling
    # IS the highest breathing RPE still normal for the type)
    if rpe_lungs is not None and rpe_lungs > RPE_BREATH_CEILING.get(wtype, 10):
        quality = "partial"
    # partial: pacing degraded but not collapsed (steady only)
    if wtype in STEADY_TYPES and pacing is not None and 0.70 <= pacing < 0.80:
        quality = "partial"
    # partial: elevated (but not extreme) aerobic decoupling
    if decoupling_valid and decoupling_pct is not None and 10 <= decoupling_pct <= 15:
        quality = "partial"

    return quality


# ── vs_plan (execution against intent) ────────────────────────────────────────────────

def _pace_verdict(executed: float | None, target: float | None) -> str:
    """Slower than target by more than the tolerance → under; otherwise on_target.
    Beating the target pace is not 'over' — over comes from extra reps/distance."""
    if not executed or not target:
        return "on_target"
    slower_by = executed - target
    if slower_by > max(target * 0.03, 3):  # >3% and >3 s/km
        return "under"
    return "on_target"


def derive_vs_plan(s: dict) -> str:
    plan = _plan_targets(s)
    if not plan:
        return "unplanned"

    wtype = _session_type(s)
    work = _work_laps(s)
    planned_reps = plan.get("work_rep_count")
    target_pace = plan.get("work_pace_target_sec_km")

    # interval sessions: reps first, then pace
    if wtype in INTERVAL_TYPES and planned_reps and planned_reps > 1:
        reps = len(work)
        if reps and reps < planned_reps:
            return "under"
        if reps and reps > planned_reps:
            return "over"
        return _pace_verdict(_executed_work_pace(work) or s.get("avg_pace_sec_per_km"),
                             target_pace)

    # continuous sessions: pace target if there is one, else distance
    if target_pace:
        return _pace_verdict(_executed_work_pace(work) or s.get("avg_pace_sec_per_km"),
                             target_pace)

    planned_dist = plan.get("work_distance_m") or plan.get("target_distance_m")
    if planned_dist:
        exec_dist = _executed_work_distance(s)
        if exec_dist:
            if exec_dist < planned_dist * 0.9:
                return "under"
            if exec_dist > planned_dist * 1.1:
                return "over"
    return "on_target"


# ── key_signal (one factual sentence — the fact the model interprets) ──────────────────

def _is_fading(work: list[dict]) -> bool:
    """Work-rep pace rose meaningfully from first to last (the legs gave out)."""
    paces = [_pace(lap) for lap in work if _pace(lap)]
    return len(paces) >= 2 and paces[-1] > paces[0] * 1.03


def _ran_above_envelope(s: dict) -> bool:
    """An aerobic session that drifted above its easy envelope, by zones or by breath."""
    wtype = _session_type(s)
    z = _zone_dist(s)
    env = ZONE_TARGETS.get(wtype, [])
    if z and env and sum(z.get(zn, 0.0) for zn in env) < 0.65:
        return True
    rpe = _breath_rpe(s)
    ceiling = RPE_BREATH_CEILING.get(wtype)
    return rpe is not None and ceiling is not None and rpe > ceiling


def derive_key_signal(s: dict, hr_max: int = ATHLETE_HR_MAX) -> str:
    wtype = _session_type(s)
    plan = _plan_targets(s)
    work = _work_laps(s)
    fb = _feedback(s)
    flags = s.get("flags") or []
    vs = derive_vs_plan(s)
    sq = derive_stimulus_quality(s)

    # session cut short of the planned reps
    planned_reps = (plan or {}).get("work_rep_count")
    if planned_reps and work and len(work) < planned_reps:
        if fb.get("achilles_flag"):
            why = " when the Achilles flared"
        elif (fb.get("rpe_legs") or 0) >= 8 or fb.get("legs") in ("heavy", "dead"):
            why = " on heavy legs"
        else:
            why = ""
        return f"Cut to {len(work)} of {planned_reps} reps{why}."

    # high-intensity fade: pace bled away while the heart never reached its ceiling
    if wtype == "vo2" and _is_fading(work):
        peak_hr = max((lap.get("avg_hr") or 0) for lap in work)
        if hr_max and peak_hr and peak_hr < 0.95 * hr_max:
            return "Pace faded across the reps while heart rate stayed below max."
        return "Pace faded across the reps."

    # aerobic day that ran hot
    if wtype in AEROBIC_TYPES and _ran_above_envelope(s):
        return "An easy-day run that drifted above easy."

    # the felt-vs-cost gap: comfortable, but the body worked harder than the pace shows
    if (fb.get("rpe_breath") or fb.get("rpe_lungs") or 99) <= 5 and "hr_drift" in flags:
        return "Felt smooth, but the heart worked harder than the pace usually costs."

    # honest miss / overreach
    if vs == "under":
        return "Came in under the target pace."
    if vs == "over":
        return "Did more work than prescribed."

    # clean
    if sq == "complete" and vs == "on_target":
        if wtype in INTERVAL_TYPES and planned_reps:
            return f"Held target across all {planned_reps} reps."
        if wtype == "long":
            return "Controlled aerobic long run, on plan."
        return "Executed on plan."
    return "Session completed."


# ── convenience ───────────────────────────────────────────────────────────────────────

def derive_signals(s: dict) -> dict:
    """All three deterministic signals for a session."""
    return {
        "stimulus_quality": derive_stimulus_quality(s),
        "vs_plan": derive_vs_plan(s),
        "key_signal": derive_key_signal(s),
    }


# ── demo ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    faded_vo2 = {
        "activity_type": "vo2",
        "avg_pace_sec_per_km": 230, "avg_hr": 170, "max_hr": 178,
        "zone_dist": {"Z2": 0.1, "Z3": 0.2, "Z4": 0.3, "Z5": 0.4},
        "flags": ["pace_fade"],
        "laps": [
            {"lap_type": "work", "distance_m": 800, "duration_sec": p * 800 // 1000,
             "avg_hr": h, "avg_pace_sec_per_km": p}
            for p, h in zip([184, 187, 192, 199, 205, 205], [172, 175, 176, 177, 177, 178])
        ],
        "feedback": {"rpe_breath": 7, "rpe_legs": 9, "achilles_flag": False},
        "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
    }
    clean_threshold = {
        "activity_type": "threshold",
        "avg_pace_sec_per_km": 244, "avg_hr": 162, "max_hr": 175,
        "zone_dist": {"Z2": 0.15, "Z3": 0.45, "Z4": 0.4},
        "laps": [
            {"lap_type": "work", "distance_m": 2000, "duration_sec": p * 2,
             "avg_hr": h, "avg_pace_sec_per_km": p}
            for p, h in zip([238, 239, 238, 240], [160, 163, 164, 166])
        ],
        "feedback": {"rpe_breath": 7, "rpe_legs": 6, "achilles_flag": False},
        "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240},
    }

    for name, session in (("faded_vo2", faded_vo2), ("clean_threshold", clean_threshold)):
        print(f"\n[{name}]")
        for signal, value in derive_signals(session).items():
            print(f"  {signal:18} {value}")
    print()

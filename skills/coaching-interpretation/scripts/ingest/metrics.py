"""
Per-session metrics computed from the laps — pacing consistency and aerobic decoupling.

These are the two signals derive_signals.py consumes but does not compute: it reads
`pacing_consistency`, `decoupling_pct`, and `decoupling_valid` off the session if present,
and only falls back to its own pacing estimate for steady types. Filling them in here is
what lets `stimulus_quality` see a pacing collapse or aerobic drift that the summary alone
can't show. So this is the piece that gives an interval / long-run read its teeth back.

Distilled from the lab's derive_metrics.py (which computed the same from FIT laps), adapted
to the lap shape ingest/intervals_icu produces and to stdlib only. Pure functions — no
network, no model — so the logic is fully unit-tested.
"""

from __future__ import annotations

import statistics

# Decoupling is only meaningful on a long, steady effort. Below this it is noise.
_MIN_STEADY_SEC = 2700          # 45 min
# Above this share of Z5+Z6 the session is interval work, where decoupling doesn't apply.
_INTERVAL_Z5_Z6 = 0.15
# Paces slower than this (s/km) are standing rests, not running — excluded from pacing.
_REST_PACE_SEC_KM = 400


def pacing_consistency(laps: list[dict]) -> float | None:
    """1 - (stdev / mean) of the running laps' paces, in [0, 1]. None with fewer than two
    usable laps. Recovery laps and standing rests are excluded so a session's floats don't
    masquerade as poor pacing."""
    paces = [
        l["avg_pace_sec_per_km"] for l in laps
        if l.get("lap_type") != "recovery"
        and l.get("avg_pace_sec_per_km")
        and l["avg_pace_sec_per_km"] < _REST_PACE_SEC_KM
    ]
    if len(paces) < 2:
        return None
    mean = statistics.mean(paces)
    if mean <= 0:
        return None
    return round(max(0.0, 1.0 - statistics.pstdev(paces) / mean), 3)


def decoupling(laps: list[dict], duration_sec: int | None,
               zone_dist: dict | None = None) -> tuple[float | None, bool]:
    """Aerobic decoupling: how much the pace-to-heart-rate efficiency drifted from the
    first half of the run to the second. Returns (decoupling_pct, valid).

    Gated to long steady efforts — too short, too few laps, or interval-intensity sessions
    return (None, False), matching the lab's rule that this only means something on
    sustained aerobic work."""
    if not duration_sec or duration_sec < _MIN_STEADY_SEC or len(laps) < 2:
        return None, False
    z = zone_dist or {}
    if z.get("Z5", 0) + z.get("Z6", 0) > _INTERVAL_Z5_Z6:
        return None, False

    mid = duration_sec / 2
    elapsed = 0.0
    first: list[dict] = []
    second: list[dict] = []
    for lap in laps:
        (first if elapsed < mid else second).append(lap)
        elapsed += lap.get("duration_sec") or 0

    def _avg(rows: list[dict], key: str) -> float | None:
        vals = [r[key] for r in rows if r.get(key)]
        return statistics.mean(vals) if vals else None

    hr1, hr2 = _avg(first, "avg_hr"), _avg(second, "avg_hr")
    pace1, pace2 = _avg(first, "avg_pace_sec_per_km"), _avg(second, "avg_pace_sec_per_km")
    if not all((hr1, hr2, pace1, pace2)):
        return None, False

    ef1, ef2 = pace1 / hr1, pace2 / hr2          # seconds per km per beat
    return round(abs(ef2 - ef1) / ef1 * 100, 2), True


def enrich_session(session: dict) -> dict:
    """Compute pacing consistency and decoupling from the session's laps and fold them
    into the session dict, where derive_signals reads them. No-op without laps. Mutates
    and returns the session."""
    laps = session.get("laps") or []
    if not laps:
        return session

    pc = pacing_consistency(laps)
    if pc is not None:
        session["pacing_consistency"] = pc

    pct, valid = decoupling(laps, session.get("duration_sec"), session.get("zone_dist"))
    session["decoupling_valid"] = valid
    if pct is not None:
        session["decoupling_pct"] = pct

    return session

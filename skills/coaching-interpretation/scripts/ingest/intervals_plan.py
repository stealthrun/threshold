"""
Pull the planned calendar from intervals.icu and distil it into the `plan_targets` the
core's `vs_plan` reasons against — so "on target / under / over" is measured against what
was actually prescribed, not the session in a vacuum.

Layer 2 (see docs/ARCHITECTURE.md). Reuses the credentials + HTTP seam from
`intervals_icu`, so auth lives in exactly one place.

Distilled from the lab's `fetch_plan.py` — the events endpoint and the `workout_doc`
structure are taken from working production code, so the shape here is verified, not
guessed. Trimmed to the public `plan_targets` contract and stdlib only.

Limitation: a workout prescribed as %pace (intensity relative to threshold) needs an
athlete threshold-pace config to resolve to an absolute pace. Here such a workout's reps
and distance are still captured; only its pace target is left None. Absolute (secs/km)
targets resolve fully. (The lab resolves %pace via a calibrated threshold pace; that
config is out of scope for the public core.)

    python3 -m ingest.intervals_plan      # demo (needs the intervals env vars)
"""

from __future__ import annotations

from datetime import date, timedelta

from ingest.intervals_icu import BASE_URL, Credentials, IntervalsError, _get  # noqa: F401

# Within a repeat block, a step counts as work if its pace is within this fraction of the
# block's fastest paced step. Recovery floats are slower and fall outside it. (The lab uses
# pace-vs-threshold percent; without a threshold config we discriminate within the block.)
_WORK_PACE_TOLERANCE = 1.12


# ── Fetch ─────────────────────────────────────────────────────────────────────────────

def fetch_events(creds: Credentials, oldest: str, newest: str) -> list[dict]:
    """Planned WORKOUT events for the inclusive date range [oldest, newest] (ISO dates)."""
    return _get(f"/athlete/{creds.athlete_id}/events",
                {"oldest": oldest, "newest": newest, "category": "WORKOUT"}, creds) or []


# ── workout_doc → plan_targets (the parse, distilled from the lab) ─────────────────────

def _step_pace_secs_km(step: dict) -> int | None:
    """Absolute pace target of a step in seconds/km, or None if it isn't given in
    secs/km (a start/end range collapses to its midpoint)."""
    pace = step.get("pace") or {}
    if pace.get("units") != "secs/km":
        return None
    val = pace.get("value")
    if val is None:
        start, end = pace.get("start"), pace.get("end")
        if start is not None and end is not None:
            val = (start + end) / 2
        else:
            val = start if start is not None else end
    return round(val) if val else None


def _work_segments(steps: list[dict]) -> list[dict]:
    """The work efforts among a set of steps: warmup/cooldown dropped, then recovery
    floats dropped by pace (slower than the fastest paced step) — or, when nothing is
    paced, the distance-targeted steps."""
    body = [s for s in steps if not (s.get("warmup") or s.get("cooldown"))]
    paces = [p for p in (_step_pace_secs_km(s) for s in body) if p]
    fastest = min(paces) if paces else None

    def is_work(step: dict) -> bool:
        p = _step_pace_secs_km(step)
        if p is not None and fastest is not None:
            return p <= fastest * _WORK_PACE_TOLERANCE
        return bool(step.get("distance"))

    return [s for s in body if is_work(s)]


def _main_set(doc: dict) -> tuple[int, list[dict]]:
    """(rep_count, work_segments_in_one_rep). intervals.icu nests a repeated set as a step
    carrying its own `steps` and a `reps` count; otherwise the top-level work leaves are
    treated as a single rep so totals never double-count."""
    steps = doc.get("steps") or []
    repeats = [s for s in steps if s.get("steps") and (s.get("reps") or 0) >= 1]
    if repeats:
        main = max(repeats, key=lambda b: len(b.get("steps") or []))
        work = _work_segments(main.get("steps") or [])
        if work:
            return int(main.get("reps") or 1), work
    work = _work_segments(steps)
    return (1, work) if work else (0, [])


def _targets_from_doc(doc: dict) -> dict:
    """The structured part of plan_targets from a workout_doc: rep count, total work
    distance, and a duration-weighted blend of the work paces."""
    reps, work = _main_set(doc)
    if not work:
        return {}
    seg_dist = sum(s.get("distance") or 0 for s in work)
    pace_items = [(p, (s.get("duration") or 1)) for s in work
                  if (p := _step_pace_secs_km(s)) is not None]
    blended = (round(sum(p * w for p, w in pace_items) / sum(w for _, w in pace_items))
               if pace_items else None)
    out: dict = {"work_rep_count": reps}
    if seg_dist:
        out["work_distance_m"] = round(seg_dist * reps)
    if blended:
        out["work_pace_target_sec_km"] = blended
    return out


def event_to_plan_targets(event: dict) -> dict | None:
    """One planned event → the `plan_targets` contract (None if it carries no usable
    target). Falls back to the event-level distance when there's no structured doc."""
    targets = _targets_from_doc(event.get("workout_doc") or {})
    if not targets.get("work_distance_m"):
        dist = (event.get("workout_doc") or {}).get("distance") or event.get("distance")
        if dist:
            targets["work_distance_m"] = round(dist)
    if not targets:
        return None
    if event.get("name"):
        targets["name"] = event["name"]
    return targets


# ── Matching plans to sessions by date ─────────────────────────────────────────────────

def plan_targets_by_date(creds: Credentials, oldest: str, newest: str) -> dict[str, dict]:
    """{date: plan_targets} for the range. On a multi-event day, the entry with the
    largest work distance wins (the main session, not a warmup save)."""
    by_date: dict[str, dict] = {}
    for ev in fetch_events(creds, oldest, newest):
        d = (ev.get("start_date_local") or "")[:10]
        pt = event_to_plan_targets(ev)
        if not d or not pt:
            continue
        existing = by_date.get(d)
        if not existing or (pt.get("work_distance_m") or 0) > (existing.get("work_distance_m") or 0):
            by_date[d] = pt
    return by_date


def attach_plans(sessions: list[dict], plans_by_date: dict[str, dict]) -> list[dict]:
    """Set `plan_targets` on each session from the matching planned day. Never overwrites
    a plan a session already carries. Mutates and returns the sessions."""
    for s in sessions:
        if s.get("plan_targets"):
            continue
        pt = plans_by_date.get(s.get("date"))
        if pt:
            s["plan_targets"] = pt
    return sessions


def fetch_recent_with_plan(creds: Credentials, weeks: int = 4,
                           today: date | None = None) -> tuple[list[dict], list[dict]]:
    """The convenience the skill calls: the last `weeks` weeks of runs with their planned
    targets attached, plus the recent-week summaries. (sessions newest-first, recent_weeks)."""
    from ingest.intervals_icu import fetch_recent

    sessions, recent = fetch_recent(creds, weeks=weeks, today=today)
    dates = [s["date"] for s in sessions if s.get("date")]
    if dates:
        attach_plans(sessions, plan_targets_by_date(creds, min(dates), max(dates)))
    return sessions, recent


# ── demo (network-gated) ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        creds = Credentials.from_env()
    except IntervalsError as exc:
        print(f"  {exc}")
        print("  Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY, then re-run.")
        raise SystemExit(0)

    print(f"Fetching the last 4 weeks (runs + plan) for athlete {creds.athlete_id}…")
    sessions, _ = fetch_recent_with_plan(creds, weeks=4)
    planned = [s for s in sessions if s.get("plan_targets")]
    print(f"\n{len(sessions)} run(s), {len(planned)} with a matched plan:")
    for s in sessions[:12]:
        pt = s.get("plan_targets")
        tag = ""
        if pt:
            tag = f"  plan: {pt.get('work_rep_count') or '?'} reps"
            if pt.get("work_pace_target_sec_km"):
                m, sec = divmod(pt["work_pace_target_sec_km"], 60)
                tag += f" @ {m}:{sec:02d}/km"
        print(f"  {s['date']}  {s['activity_type']:9} {s['distance_km']}km{tag}")
    print()

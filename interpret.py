"""
The interpretation step — the LLM half that turns the deterministic signals into the
coach's read. This is the one place the prompt is assembled, and the one place the model
is called.

The pipeline, end to end:

  1. derive the deterministic signals (derive_signals.py) — what happened, in plain Python.
  2. assemble ONE prompt from four sources that each own their part:
       - the coaching framework (references/coaching_framework.md) — the athlete model
         the read is graded against;
       - VOICE_GUARDRAILS (coach_voice.py) — how the coach may speak;
       - the session facts + the derived signals — what to interpret;
       - the recent-week context — what turns a number into a trend.
  3. call the model (the local `claude` CLI) to write the read.
  4. self-check the output with voice_violations (coach_voice.py); if it leaks a forbidden
     metric or word, regenerate ONCE with the specific leak named, then return.

Why one assembly site: in the lab the same voice rule drifted across copy-pasted prompt
sites. Here the rule lives in coach_voice.py and the framework in its own reference file;
this module only composes them. The model's job stays small — interpret given signals,
never invent them — which is the whole design (see docs/DESIGN.md).

Why the CLI: the public core stays dependency-light and runs cold with no SDK and no API
key wired in. call_claude shells to `claude -p` and is the single seam to swap if that
ever changes.

Run me on the golden sessions:

    python3 interpret.py
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from coach_voice import VOICE_GUARDRAILS, voice_violations
from derive_signals import derive_signals

# ── The coaching framework (single source of truth, read from its reference file) ─────

_FRAMEWORK_PATH = (
    Path(__file__).parent
    / "skills" / "coaching-interpretation" / "references" / "coaching_framework.md"
)


def _load_framework() -> str:
    """The athlete model the read is written against. Read from the same markdown a
    human reads, so the generation prompt and the grading rubric can never diverge."""
    try:
        return _FRAMEWORK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ── The role + structure instructions (distilled from the lab's session_brief) ────────

_SYSTEM = (
    "You are a precision endurance coach writing the post-session read for the athlete "
    "described in the COACHING FRAMEWORK below. You are given that framework, the "
    "deterministic SIGNALS for the session (what happened, already computed), the "
    "objective SESSION facts and per-rep work laps, how it FELT, and the RECENT WEEKS "
    "for trend.\n\n"
    "Write one flowing paragraph, about 4 to 6 sentences, a coach talking straight to "
    "the athlete. Cover, in order and only where there is something real to say:\n"
    "1. How execution compared to the plan, using actual against target where given "
    "(e.g. '3:58/km against a 4:00/km target, all the reps').\n"
    "2. What the session meant for THIS athlete's engine and limiters — read the signals "
    "through the framework, never as generic advice. Name the mechanism, not just the "
    "outcome.\n"
    "3. The gap between how it FELT and what the body actually did, integrated into the "
    "read rather than listed.\n"
    "4. What the recent weeks mean for readiness right now — the trend, not the totals.\n"
    "5. End on the ONE thing to carry forward and a concrete action for the next 48 "
    "hours.\n\n"
    "Be honest and specific. If the session was good and the body is fine, say so plainly "
    "and do not manufacture concern. No greeting, no headers, no lists. Do not restate "
    "raw distance or duration the athlete already knows. Output ONLY the read."
)


# ── Light formatting helpers (stdlib only; pace/zones for the prompt, not the output) ─

def _fmt_pace(sec_per_km) -> str:
    """Seconds-per-km -> 'm:ss/km'. Pace times are athlete-facing and allowed."""
    if not sec_per_km:
        return "n/a"
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def _zone_buckets(zone_dist: dict | None) -> str:
    """Collapse per-zone fractions into a coarse aerobic/threshold/anaerobic split for
    the prompt. (Lives only in the prompt; the voice guard keeps it out of the output.)"""
    z = zone_dist or {}
    aerobic = round((z.get("Z1", 0) + z.get("Z2", 0)) * 100)
    threshold = round((z.get("Z3", 0) + z.get("Z4", 0)) * 100)
    anaerobic = round((z.get("Z5", 0) + z.get("Z6", 0)) * 100)
    return f"aerobic {aerobic}% / threshold {threshold}% / anaerobic {anaerobic}%"


def _fmt_plan(plan: dict | None) -> list[str]:
    if not plan:
        return ["  unplanned session"]
    bits = []
    if plan.get("work_rep_count"):
        bits.append(f"{plan['work_rep_count']} reps planned")
    if plan.get("work_pace_target_sec_km"):
        bits.append(f"target pace {_fmt_pace(plan['work_pace_target_sec_km'])}")
    if plan.get("work_distance_m"):
        bits.append(f"{round(plan['work_distance_m'] / 1000, 1)}km work distance")
    return [f"  {', '.join(bits)}"] if bits else ["  (targets unspecified)"]


def _fmt_work_laps(laps: list[dict] | None) -> str | None:
    work = [l for l in (laps or []) if l.get("lap_type") == "work"]
    if not work:
        return None
    return "  ".join(
        f"{_fmt_pace(l.get('avg_pace_sec_per_km'))}@{l.get('avg_hr') or '-'}"
        for l in work[:16]
    )


def _fmt_recent_weeks(recent_weeks: list[dict] | None) -> list[str]:
    """Trailing context, newest first. Each week: a label, optional volume/session
    count, and a one-line read. Shape is the public contract; what the trend MEANS is
    the model's job."""
    if not recent_weeks:
        return ["  none provided"]
    out = []
    for w in recent_weeks:
        label = w.get("label", "week")
        stats = []
        if w.get("volume_km") is not None:
            stats.append(f"{w['volume_km']}km")
        if w.get("sessions") is not None:
            stats.append(f"{w['sessions']} sessions")
        head = f"{label}: {', '.join(stats)}" if stats else label
        read = w.get("read")
        out.append(f"  {head}{' — ' + read if read else ''}")
    return out


# ── Context assembly: the session facts + signals + feel + recent weeks ────────────────

def build_context(session: dict, recent_weeks: list[dict] | None = None) -> str:
    """Render one session (and its derived signals) into the prompt's data block."""
    signals = derive_signals(session)
    fb = session.get("feedback") or {}
    flags = session.get("flags") or []

    lines = [
        "SIGNALS (deterministic, already computed — interpret these, do not recompute):",
        f"  stimulus_quality: {signals['stimulus_quality']}",
        f"  vs_plan: {signals['vs_plan']}",
        f"  key_signal: {signals['key_signal']}",
        "",
        "SESSION:",
        f"  type: {session.get('activity_type')}  distance: {session.get('distance_km')}km",
        f"  avg pace: {_fmt_pace(session.get('avg_pace_sec_per_km'))}"
        f"  avg HR: {session.get('avg_hr')}  max HR: {session.get('max_hr')}",
        f"  intensity split: {_zone_buckets(session.get('zone_dist'))}",
        f"  flags: {', '.join(flags) if flags else 'none'}",
        "",
        "PLAN:",
        *_fmt_plan(session.get("plan_targets")),
    ]

    work_reps = _fmt_work_laps(session.get("laps"))
    if work_reps:
        lines += ["", "WORK REPS (pace@hr):", f"  {work_reps}"]

    lines += [
        "",
        "FELT:",
        f"  feel: {fb.get('feel', 'not logged')}",
        f"  effort — legs: {fb.get('rpe_legs', 'n/a')}/10  breath: "
        f"{fb.get('rpe_breath', fb.get('rpe_lungs', 'n/a'))}/10",
        f"  Achilles niggle: {'YES' if fb.get('achilles_flag') else 'no'}",
        "",
        "RECENT WEEKS (newest first):",
        *_fmt_recent_weeks(recent_weeks),
    ]
    return "\n".join(lines)


def build_prompt(session: dict, recent_weeks: list[dict] | None = None) -> str:
    """Assemble the full prompt in ONE place: role + framework + voice + data. This is
    the single composition site the design depends on; the unit test pins its contents."""
    return (
        f"{_SYSTEM}\n\n"
        f"COACHING FRAMEWORK:\n{_load_framework()}\n\n"
        f"{VOICE_GUARDRAILS}\n\n"
        f"{build_context(session, recent_weeks)}"
    )


# ── The model call (the one seam: shell to the local `claude` CLI) ─────────────────────

def _strip_fence(text: str) -> str:
    """Strip a leading ```/```text fence and trailing ``` from a model response."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    return t.strip()


def call_claude(prompt: str, timeout: int = 120) -> str | None:
    """Run the local `claude` CLI with one prompt and return its stdout (fence-stripped),
    or None if claude is unavailable, errors, or times out — so callers degrade to 'no
    read' rather than crash."""
    if not shutil.which("claude"):
        return None
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            print(f"   ! claude exited {result.returncode}: {result.stderr.strip()[:120]}")
            return None
        return _strip_fence(result.stdout) or None
    except Exception as exc:  # subprocess.TimeoutExpired, OSError, ...
        print(f"   ! claude call failed: {exc}")
        return None


# ── The retry trigger: the half a prompt can't guarantee ───────────────────────────────

def _correction(violations: list[tuple[str, str]]) -> str:
    """A targeted regeneration instruction naming the exact leaks the guard caught."""
    leaked = ", ".join(sorted({f"{cat} ({hit!r})" for cat, hit in violations}))
    return (
        "\n\nYour previous read leaked forbidden content the athlete must never see: "
        f"{leaked}. Rewrite the read with the SAME coaching content but translate those "
        "into plain body language. Output ONLY the corrected read."
    )


def interpret(
    session: dict,
    recent_weeks: list[dict] | None = None,
    timeout: int = 120,
) -> str | None:
    """Turn one session into the coach's read: derive signals, assemble the prompt, call
    the model, then voice-check the output and regenerate ONCE if it leaks. Returns the
    clean read, the best attempt if the leak survives the retry, or None if the model is
    unavailable."""
    prompt = build_prompt(session, recent_weeks)

    brief = call_claude(prompt, timeout=timeout)
    if not brief:
        return None

    violations = voice_violations(brief)
    if not violations:
        return brief

    retry = call_claude(prompt + _correction(violations), timeout=timeout)
    return retry or brief


# ── demo: run the engine on two goldens and gate the output ───────────────────────────

if __name__ == "__main__":
    faded_vo2 = {
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
                     "feel": "legs cooked by rep 4, lungs still had room"},
        "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
    }
    clean_threshold = {
        "activity_type": "threshold",
        "distance_km": 12.0, "avg_pace_sec_per_km": 244, "avg_hr": 162, "max_hr": 175,
        "zone_dist": {"Z2": 0.15, "Z3": 0.45, "Z4": 0.4},
        "laps": [
            {"lap_type": "work", "distance_m": 2000, "duration_sec": p * 2,
             "avg_hr": h, "avg_pace_sec_per_km": p}
            for p, h in zip([238, 239, 238, 240], [160, 163, 164, 166])
        ],
        "feedback": {"rpe_breath": 7, "rpe_legs": 6, "achilles_flag": False,
                     "feel": "controlled, smooth all the way through"},
        "plan_targets": {"work_rep_count": 4, "work_pace_target_sec_km": 240},
    }
    recent_weeks = [
        {"label": "this week", "volume_km": 78, "sessions": 6,
         "read": "Right at the top of your tolerance; legs heavy by midweek."},
        {"label": "week -1", "volume_km": 82, "sessions": 6,
         "read": "Biggest week of the block, absorbed it well."},
        {"label": "week -2", "volume_km": 70, "sessions": 5, "read": "Steady build."},
    ]

    for name, session in (("faded_vo2", faded_vo2), ("clean_threshold", clean_threshold)):
        print(f"\n{'=' * 72}\n[{name}]\n{'=' * 72}")
        brief = interpret(session, recent_weeks)
        if not brief:
            print("  (no read — claude CLI unavailable)")
            continue
        violations = voice_violations(brief)
        verdict = "CLEAN" if not violations else f"{len(violations)} violation(s)"
        print(f"\n{brief}\n")
        print(f"voice guard: {verdict}")
        for category, hit in violations:
            print(f"  x {category}: {hit!r}")
    print()

"""
The LLM judge — the second layer of the quality gate.

The deterministic voice guard (coach_voice.voice_violations) catches what a regex can
see: leaked zones, percentages, analyst jargon. It cannot tell whether the read actually
engaged the scenario's coaching signal, spoke as a coach rather than an analyst, or
manufactured concern the data doesn't support. That judgment is what this scores.

The judge is itself a `claude` call (the same local CLI the read uses), prompted to grade
ONE read against ONE golden's rubric and return structured JSON. It is machine-facing, so
it may name zones and metrics freely — the voice rules bind the coach being graded, not
the grader.

The five criteria are kept parallel to interpret.py's five jobs, so a judge failure points
straight back at the instruction that slipped. A read passes only if EVERY criterion
passes and the overall clears PASS_THRESHOLD — conservative on purpose; the harness should
flag, not flatter.

The judge model is whatever the local `claude` CLI is configured to use. That's fine for a
relative baseline (runs are compared to each other, not to an absolute); a later phase can
pin a stronger judge model explicitly.
"""

from __future__ import annotations

import json

from interpret import call_claude

# (key, what a PASS means). Parallel to interpret.py's _SYSTEM five jobs.
CRITERIA: list[tuple[str, str]] = [
    (
        "addresses_core_signal",
        "Engages the central coaching signal of THIS scenario (the must_address points) "
        "rather than a generic recap that could fit any session.",
    ),
    (
        "coach_not_analyst",
        "Reads as a coach talking straight to the athlete and interpreting what the body "
        "did — not a metrics report or a neutral data summary.",
    ),
    (
        "evidence_grounded",
        "Ties its claims to the actual session (the reps, the pace, the feel, the trend) "
        "with specifics, instead of vague encouragement.",
    ),
    (
        "actionable_close",
        "Ends on one clear thing to carry forward and a concrete action for the next 48 "
        "hours, not a generic sign-off.",
    ),
    (
        "no_false_signal",
        "Does not manufacture concern the data doesn't support, nor over-coach a clean or "
        "easy day (the must_not points).",
    ),
]

PASS_THRESHOLD = 4  # overall 1-5; >= this is a passing read


def _rubric_block() -> str:
    return "\n".join(f"  - {key}: {meaning}" for key, meaning in CRITERIA)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"  - {x}" for x in items) if items else "  - (none)"


def build_prompt(golden: dict, brief: str) -> str:
    shape = (
        '{"criteria": {"<each criterion key above>": {"pass": true, "note": "<=12 words"}}, '
        '"overall": <integer 1-5>, '
        '"verdict": "<one sentence: the single biggest strength or issue>"}'
    )
    return (
        "You are a strict head coach auditing a junior coach's post-session read for a "
        "single athlete. You know the athlete: speed-dominant 400m/800m engine, whose real "
        "limiters are aerobic durability and weekly volume tolerance, with Achilles "
        "tendinopathy risk on high-speed work. Grade ONLY the read below. Be hard to "
        "please: a generic, hedging, or analyst-voiced read should fail, even if nothing "
        "in it is wrong.\n\n"
        f"SCENARIO (what this session is testing):\n  {golden['isolates']}\n\n"
        f"THIS READ MUST ENGAGE:\n{_bullets(golden['must_address'])}\n\n"
        f"THIS READ MUST NOT:\n{_bullets(golden['must_not'])}\n\n"
        f"GRADE EACH CRITERION as pass=true/false:\n{_rubric_block()}\n\n"
        f'THE READ TO GRADE:\n"""\n{brief}\n"""\n\n'
        f"Return ONLY a JSON object, no prose around it, in exactly this shape:\n{shape}"
    )


def _parse_json(raw: str) -> dict | None:
    """call_claude already strips any code fence; parse what's left as a JSON object."""
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def judge_brief(golden: dict, brief: str) -> dict | None:
    """Grade one read against one golden. Returns the parsed judge dict, or None if claude
    is unavailable or the output won't parse (the caller treats that as an error row, not a
    fail — a bad grader is not a bad read)."""
    raw = call_claude(build_prompt(golden, brief), timeout=120)
    if not raw:
        return None
    data = _parse_json(raw)
    if not isinstance(data, dict) or "criteria" not in data:
        return None
    return data


def passed(judge_result: dict) -> bool:
    """A read passes the judge only if every criterion passes AND overall clears the bar."""
    crit = judge_result.get("criteria") or {}
    all_crit = all(bool(v.get("pass")) for v in crit.values()) if crit else False
    try:
        overall_ok = int(judge_result.get("overall", 0)) >= PASS_THRESHOLD
    except (TypeError, ValueError):
        overall_ok = False
    return all_crit and overall_ok

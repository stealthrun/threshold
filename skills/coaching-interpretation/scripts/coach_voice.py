"""
The voice contract — the single rule every athlete-facing LLM call obeys, plus the
machine-checkable form of that rule.

`VOICE_GUARDRAILS` is the contract handed to the model in prose: translate the signal,
never quote the number; a coach talking, not an analyst. `voice_violations` is that same
contract enforced by a regex on the model's OUTPUT — the half a prompt can't guarantee.
A prompt can ask for clean prose; it cannot prove the prose is clean. This does.

They live in one module on purpose: when the forbidden vocabulary changes, the rule and
its checker move together and cannot drift. (In the larger system, drift between four
copy-pasted guardrails is exactly the bug this convergence fixed.)

Today this is used as a deterministic pass/fail gate by the eval harness (see evals/).
It is built so a later phase can wire it straight into the generation call as a retry
trigger: generate, scan, regenerate if dirty.

Run me:

    python3 coach_voice.py
"""

import re

# ── The one voice contract every athlete-facing prompt appends ───────────────────────

VOICE_GUARDRAILS = (
    "VOICE — write to the athlete as 'you', never about them in the third person "
    "('the athlete'). Plain language, a coach talking. Translate every signal into "
    "what it means for the body; never quote the raw number behind it. "
    "Allowed: pace times (e.g. 3:58/km) and rep counts in numerals (e.g. 8x1km, "
    "4x(600m-500m-400m)) — the athlete reads those daily. "
    "Never surface: zone codes (Z1-Z5), percentages, decimal scores (e.g. 0.78), or "
    "any of these words — pacing consistency, decoupling, stimulus quality, aerobic "
    "horsepower, stacking, fragmentation, residual-fatigue, hidden cost, masking, "
    "absorbing, degrading, T1, T2, LT1, VO2 (say 'VO2 max' if you must). "
    "No filler phrases, no markdown, no headers, no bullet points, and no em dashes "
    "as the character."
)


# ── The voice guard: the machine-checkable form of VOICE_GUARDRAILS ──────────────────
#
# A regex can only see SURFACE leaks — but those are exactly the failures that used to
# ship: a stray "Z5", a "0.78", a bare "VO2". Categories are kept separate so a failure
# says WHICH rule tripped, not just "dirty":
#
#   zone_code      Z1-Z6 zone labels
#   percentage     a literal % or the word "percent"
#   decimal_score  a 0.78-style internal score (pace is m:ss, distance is one decimal,
#                  so a two-plus-decimal number is always a leaked metric)
#   analyst_jargon the compute-side vocabulary the athlete never sees ("VO2 max" is ok)
#   taxonomy_leak  the internal week-state words (masking/absorbing/degrading)
#   em_dash        the — character (style rule)
_VIOLATION_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("zone_code", re.compile(r"\bZ[1-6]\b")),
    ("percentage", re.compile(r"%|\bpercent", re.I)),
    ("decimal_score", re.compile(r"\b\d\.\d{2,}\b")),
    (
        "analyst_jargon",
        re.compile(
            r"pacing[ _-]?consistenc|decoupl|stimulus[ _-]?qualit|"
            r"aerobic[ _-]?horsepower|\bstacking\b|fragment|"
            r"residual[ _-]?fatigue|hidden[ _-]?cost|\bLT[12]\b|\bT[12]\b|"
            r"\bVO2\b(?!\s*max)",
            re.I,
        ),
    ),
    ("taxonomy_leak", re.compile(r"\bmasking\b|\babsorbing\b|\bdegrading\b", re.I)),
    ("em_dash", re.compile(r"—")),
]


def voice_violations(text: str) -> list[tuple[str, str]]:
    """Scan a model-written brief for breaches of VOICE_GUARDRAILS. Returns
    (category, matched_substring) pairs — an empty list means the prose is clean."""
    found: list[tuple[str, str]] = []
    for category, pat in _VIOLATION_PATTERNS:
        for m in pat.finditer(text or ""):
            found.append((category, m.group(0)))
    return found


def is_clean(text: str) -> bool:
    """True when the brief surfaces none of the forbidden jargon or metrics."""
    return not voice_violations(text)


# ── Demo ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dirty = (
        "Z5 time was 38%, pacing consistency 0.78, clear decoupling in rep 4 "
        "— classic VO2 fade."
    )
    clean = (
        "Your legs hit their limit before your heart did. The pace bled away while "
        "your effort stayed under the ceiling, so the cardiovascular stimulus was "
        "diminished, not a bad day. Next time drop a rep and hold the pace."
    )

    for label, brief in (("ANALYST", dirty), ("COACH", clean)):
        violations = voice_violations(brief)
        verdict = "CLEAN" if not violations else f"{len(violations)} violation(s)"
        print(f"\n[{label}] {verdict}")
        print(f"  {brief}")
        for category, hit in violations:
            print(f"    ✗ {category}: {hit!r}")
    print()

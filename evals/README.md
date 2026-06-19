# evals — the quality gate

Before pushing the coaching read from "a prompt that usually reads okay" to something I
can change with confidence, I freeze the hard cases and score the generator against them.
After that, every prompt change is a **measured delta**, not a vibe.

The harness scores the *real* generator — the same code path the live system runs — so
what's measured here is what ships.

## What it checks — two layers, deliberately separate

1. **Voice guard** ([`../coach_voice.py`](../coach_voice.py)) — deterministic, free,
   instant. It scans the generated brief for leaked zone codes (`Z1`–`Z6`), percentages,
   `0.78`-style internal scores, analyst jargon (`pacing consistency`, `decoupling`,
   `VO2` without `max`, …), the internal week-state words (`masking`/`absorbing`/
   `degrading`), and em dashes. A regex only sees *surface* leaks — but those are exactly
   the failures that used to ship.

2. **LLM judge** — a model call grading whether the brief actually *coached*: did it
   engage this scenario's core signal, read as a coach and not an analyst, ground its
   claims in the data, end on a concrete action, and — just as important — *not*
   manufacture concern a clean session doesn't warrant. Per-criterion pass/fail plus an
   overall 1–5.

A golden **passes** only if the voice guard is clean **and** the judge passes every
criterion with overall ≥ 4. The gate is intentionally hard to please.

## The golden sessions

Eight frozen scenarios, each isolating one coaching read, all written around a real
athlete model (speed-dominant engine; aerobic durability and weekly volume tolerance are
the limiters; Achilles risk on high-speed work):

| golden | the read it isolates |
|---|---|
| `clean_threshold` | the control — hit the plan, **don't** invent concern |
| `faded_vo2` | pace faded while heart rate stayed sub-max → diminished stimulus |
| `easy_drifted_tempo` | easy run crept above easy → aerobic debt, not a bonus |
| `achilles_flare` | session cut on a niggle → backing off was the right call |
| `masking_week` | splits fine, legs flat → fatigue hiding under good numbers |
| `felt_smooth_high_cost` | felt easy, but the body worked harder than the splits |
| `long_run_on_plan` | aerobic durability — the real limiter — done right |
| `threshold_under_target` | missed the pace honestly → fatigue, not lost fitness |

Each carries a `must_address` list (what a good read has to engage) and a `must_not` list
(what it must not do) that feed the judge's rubric. A worked example is in
[`../examples/`](../examples/).

## Roadmap

- [x] Voice guard — runnable today (`python3 ../coach_voice.py`).
- [x] Golden-session design + rubric.
- [ ] `golden_sessions.py` — the eight scenarios as runnable fixtures *(Phase 3)*.
- [ ] `judge.py` + `run.py` — wire the judge to the live generator *(Phase 3)*.

The generator these score lives in the private lab and gets distilled into this repo as
the skill matures.

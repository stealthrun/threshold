---
name: coaching-interpretation
description: Interpret a single endurance training session the way a coach would, not an analyst. Given a session's metrics, its plan target, and how the athlete felt, produce a short, plain-language read of what the session meant for the body and one concrete next step. Use when an athlete wants a run interpreted in context, not just summarized into charts and zones.
---

# coaching-interpretation

> **Status: skeleton.** The interpretation prompt and helper scripts land in Phase 2.
> The output contract it targets is already real and enforced — see
> [`coach_voice.py`](../../coach_voice.py).

## What this skill does

Turns one training session into a coach's read: what the session *meant for the body*,
in the context of the athlete's recent weeks and known limiters, ending on a single
concrete next step. It is the opposite of a data dump — it never recites zones or
percentages back at the athlete.

## Inputs

A session bundle (the shape the engine assembles at runtime):

- **`activity`** — type, distance, duration, avg/max HR, pace, derived signals
  (`stimulus_quality`, `vs_plan`, `key_signal`).
- **`laps`** — per-rep work splits (pace + HR), for reading how the session evolved.
- **`feedback`** — how it felt: RPE, legs vs breath, Achilles flag, free-text notes.
- **`plan_target`** — what was prescribed, so the read is *against the plan*, not abstract.
- **`recent_weeks`** — the trailing context that turns a number into a trend.

## Output contract

A short coach's read (a few sentences) that obeys the voice contract:

- Translate every signal into what it means for the body; never quote the raw number.
- Write to the athlete as "you," in plain language.
- End on one concrete, actionable next step.
- Pass [`voice_violations`](../../coach_voice.py) with zero hits before it ships.

## How it reads a session (the pipeline this skill wraps)

1. **Deterministic signals first.** `stimulus_quality`, `vs_plan`, and `key_signal` are
   computed in plain Python ([`derive_signals.py`](../../derive_signals.py)), not by the
   model. Verifiable, tested, and free.
2. **The model interprets, not describes.** It receives those signals plus the athlete's
   recent context and produces the read. This is the only step that needs judgment.
3. **The output is gated.** `voice_violations` scans the result; a later phase regenerates
   on any leak. Quality is also held to the [`evals/`](../../evals/) golden set.

## To be filled (Phase 2)

- [x] `derive_signals.py` (repo root) — the deterministic `stimulus_quality` / `vs_plan`
      / `key_signal` derivation, distilled from the private lab. **Done** (20 tests).
- [ ] The interpretation prompt (system + the session-bundle template).
- [ ] `references/coaching_framework.md` — the athlete model the read is graded against
      (speed-dominant engine; aerobic durability and volume tolerance are the limiters;
      Achilles risk on high-speed work).

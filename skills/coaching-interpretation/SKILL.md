---
name: coaching-interpretation
description: Interpret a single endurance training session the way a coach would, not an analyst. Given a session's metrics, its plan target, and how the athlete felt, produce a short, plain-language read of what the session meant for the body and one concrete next step. Use when an athlete wants a run interpreted in context, not just summarized into charts and zones.
---

# coaching-interpretation

> **Status: live.** The deterministic signals, the athlete model, and the interpretation
> step are all in place. The output contract is real and enforced — see
> [`coach_voice.py`](../../coach_voice.py). The eval runner + judge land in Phase 3.

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

## How it reads a session (the step, end to end)

The whole step is assembled and run in one place — [`interpret.py`](../../interpret.py).
`interpret(session, recent_weeks)` does this:

1. **Derive the signals (deterministic).** `stimulus_quality`, `vs_plan`, and `key_signal`
   are computed in plain Python ([`derive_signals.py`](../../derive_signals.py)), not by
   the model. Verifiable, tested, free — *what happened*.
2. **Read against the framework.** The signals + the session facts + the recent-week
   context are interpreted *through* the athlete model in
   [`references/coaching_framework.md`](references/coaching_framework.md) — speed-dominant
   engine; aerobic durability and weekly volume tolerance are the limiters; Achilles risk
   on high-speed work. A read that ignores those limiters is describing, not coaching, and
   a clean session is read as clean (no manufactured concern). This is the only step that
   needs judgment.
3. **Write in voice.** `VOICE_GUARDRAILS` ([`coach_voice.py`](../../coach_voice.py)) is
   appended to the same prompt: translate every signal into what it means for the body,
   never quote the raw number; a coach talking, ending on one concrete next step.
4. **Self-check the guard.** `voice_violations` scans the output; if it leaks a forbidden
   metric or word, `interpret.py` regenerates **once** with the exact leak named, then
   returns. The half a prompt can't guarantee, enforced after the fact.

The prompt is composed from those four sources in a single function (`build_prompt`) so
the voice rule and the athlete model can never drift across copies. Quality is also held
to the [`evals/`](../../evals/) golden set (runner + LLM judge: Phase 3).

Run the step on a golden:

    python3 interpret.py        # derives, generates, prints the read + guard verdict

## Status

- [x] `derive_signals.py` — deterministic `stimulus_quality` / `vs_plan` / `key_signal`,
      distilled from the private lab (20 tests).
- [x] `references/coaching_framework.md` — the athlete model the read is graded against.
- [x] `interpret.py` — single-site prompt assembly, the model call, and the voice-guard
      retry (prompt-assembly + retry tests in [`tests/`](../../tests/)).
- [ ] `evals/` runner + LLM judge wired to this generator *(Phase 3)*.

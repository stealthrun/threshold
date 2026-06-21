# Design notes

The decisions behind `threshold`, written for someone evaluating how I think about
building with LLMs. Each section is a hypothesis about what an AI coaching agent
actually needs — and why the obvious approach is usually wrong.

_This documents the system's design as a whole. Pieces that currently live in the private
lab and are still being ported into this public repo are marked 🚧._

## 1. Interpret, don't describe

The thesis the whole project tests: the value isn't the data, it's the read.

Existing tools all stop at description — here are your splits, here's your zone
distribution, here's a graph. A coach never does that. A coach looks at the same numbers
and says *what they mean for your body, given the last six weeks*. The entire system is
organised around producing that second thing, and treating the first thing (charts,
percentages) as raw material the athlete should almost never see directly.

## 2. Evals before prompts

The failure mode of LLM features is that they "usually read okay" and quietly regress
the moment you tweak a prompt. The fix is to make quality measurable *before* writing the
prompt you want to ship.

So the hard cases are frozen first, as **golden sessions** — each isolating one distinct
coaching read:

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

Each golden carries two lists: `must_address` (what a good read has to engage) and
`must_not` (what it must never do). The `must_not` list is the part most people skip and
the part that matters most: the most common LLM-coach failure isn't being wrong, it's
**manufacturing insight** — inventing a fatigue story on a clean session to sound smart.
The control case (`clean_threshold`) exists specifically to catch that.

Once the goldens exist, every prompt change is a measured delta, not a vibe.

## 3. A two-layer gate

Quality here has two independent failure surfaces, so it gets two independent checks.

**Layer 1 — the voice guard (deterministic).** A regex over the model's *output*
([`coach_voice.py`](../skills/coaching-interpretation/scripts/coach_voice.py)). It can only see surface leaks — a stray `Z5`, a
`0.78`, a bare `VO2`, an em dash — but those are exactly the failures that used to ship.
It's free, instant, and it's the half a prompt fundamentally cannot guarantee: a prompt
can *ask* for clean prose; it cannot *prove* the prose is clean.

**Layer 2 — the LLM judge** ([`evals/judge.py`](../evals/judge.py)). A separate model
call grading the part a regex can't see: did the brief engage this scenario's core signal,
read as a coach and not an analyst, ground its claims in the data, end on a concrete
action — and *not* manufacture concern. Per-criterion pass/fail plus an overall 1–5. Its
five criteria are kept parallel to the generation prompt's five jobs, so a failure points
back at the instruction that slipped.

A golden passes only if the guard is clean **and** the judge passes every criterion. Hard
to please on purpose.

## 4. Deterministic where it should be, LLM where it has to be

A recurring discipline: use the model only for the part that genuinely needs judgment.

The signals — `stimulus_quality` (was the session's intent achieved), `vs_plan` (on
target / under / over / unplanned), `key_signal` (the one-sentence what-happened) — are
derived in plain Python from the data and the plan. They're deterministic, unit-tested,
and free. The LLM is handed those signals and does only the irreducibly fuzzy job:
turning them into a coach's read in the athlete's language.

This keeps the surface where the model can hallucinate small, and the surface I can test
large.

## 5. One engine, not a multi-agent panel

It's tempting (and demos well) to build a "panel": a fatigue agent, a pacing agent, an
injury agent, a coordinator. I deliberately didn't. A single engine holding the athlete's
full context produces a more coherent read than a swarm negotiating one, and it's far
easier to evaluate and debug. Restraint is the design decision — the simpler correct
architecture over the impressive-looking one.

## 6. One voice, one place

The voice contract and its checker live in the same module
([`coach_voice.py`](../skills/coaching-interpretation/scripts/coach_voice.py)). This is not incidental. Earlier, the same
guardrail was copy-pasted — slightly differently — into four prompt sites, and that drift
is what let the athlete-facing surfaces diverge. The rule (`VOICE_GUARDRAILS`, prose for
the model) and its enforcement (`voice_violations`, regex on the output) now move
together and cannot drift apart.

## 7. What's deferred, and why

Honesty is part of the design. Deliberately out of scope for this showcase:

- **The FIT-file pipeline** (parsing watch files → structured sessions) lives in the
  private lab. It's plumbing, not the interesting part.
- **Plan ingestion** from a third-party calendar — real in the lab, stubbed here with
  explicit plan targets in the goldens.
- **The web app** — a separate spike. The reasoning engine is the portfolio piece, not
  the UI.

The goal of this repo is to be *legible*, not complete. The parts that are here are the
parts worth reading.

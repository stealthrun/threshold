---
name: coaching-interpretation
description: Interpret an athlete's endurance training the way a coach would, not an analyst. Pulls recent runs from intervals.icu, reads one session against the athlete's plan, block, and recent weeks, and writes a short plain-language read of what it meant for the body and one concrete next step into their Obsidian vault. Use when an athlete wants a run interpreted in context, not summarized into charts and zones.
---

# coaching-interpretation

> **Status: live, end to end.** Fetches from intervals.icu, interprets against the athlete
> model, and records the read into the vault. The output contract is enforced — see
> [`coach_voice.py`](../../coach_voice.py). The eval runner + judge gate quality
> ([`evals/`](../../evals/)).

## What this skill does

Turns one training session into a coach's read: what the session *meant for the body*, in
the context of the athlete's recent weeks, training block, and known limiters, ending on a
single concrete next step. It is the opposite of a data dump — it never recites zones or
percentages back at the athlete. The read is saved as a linked note in the athlete's vault,
so coaching compounds over time.

## Setup (one time)

The skill reads the athlete's data from intervals.icu and writes to their Obsidian vault.

1. **intervals.icu credentials** — export two environment variables (the API key is a
   secret; it is read only from the environment, never logged or written to the vault):

       export INTERVALS_ATHLETE_ID=i12345
       export INTERVALS_API_KEY=...        # Settings → Developer on intervals.icu

2. **A vault path** — any folder Obsidian opens (it can be empty). The skill bootstraps a
   `threshold/` namespace inside it on first run, non-destructively.

## How to run it

The whole pipeline is one entry point — [`coach.py`](../../coach.py):

    python3 coach.py --vault ~/ObsidianVault                  # read the most recent run
    python3 coach.py --vault ~/ObsidianVault --activity i123  # read a specific activity
    python3 coach.py --vault ~/ObsidianVault --date 2026-06-18

**Pass the block when the athlete tells you about it.** The training block is the deepest
context tier and the one thing that can't be fetched — it's human-curated intent (what the
plan is *trying* to do right now), and it flips how an identical session reads: an
under-target effort deep in a heavy build is expected fatigue; the same miss in a taper is a
flag. Ask the athlete where they are, then thread it through:

    python3 coach.py --vault ~/ObsidianVault \
        --block-name "base build" --block-phase build \
        --block-week 6 --block-total-weeks 8 \
        --block-focus "raising weekly volume and aerobic durability"

The block, once curated, also lives in the vault under `threshold/blocks/` — read it there
to recall it on later runs.

## What happens, end to end

`coach.py` sequences the three layers (see [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md));
each step lives in its own module and this is the only place they're wired:

1. **Bootstrap the vault** ([`vault/bootstrap.py`](../../vault/bootstrap.py)) — lay down the
   `threshold/` skeleton + hub notes if missing. Idempotent, never overwrites.
2. **Fetch recent weeks** ([`ingest/intervals_plan.py`](../../ingest/intervals_plan.py)) —
   the last few weeks of runs with their planned targets attached, plus the recent-week
   trend, in one round trip.
3. **Load the focal session's detail** ([`ingest/intervals_icu.py`](../../ingest/intervals_icu.py))
   — its per-rep work laps, then the derived metrics (pacing consistency, decoupling) folded
   back in so the signals can read them.
4. **Interpret** ([`interpret.py`](../../interpret.py)) — derive the deterministic signals
   (`stimulus_quality`, `vs_plan`, `key_signal`), assemble one prompt from the framework +
   voice contract + session + block + trend, generate the read, and self-correct once if the
   voice guard catches a leak. *This is the only step that needs judgment.*
5. **Record** ([`vault/notes.py`](../../vault/notes.py)) — write the read as a linked
   activity note (wired to its week, block, type, and most similar past sessions), preserving
   anything the athlete wrote under `## Notes`.

If credentials are missing or the `claude` CLI is unavailable, the skill says so plainly and
records nothing rather than failing — read [`coach.py`](../../coach.py)'s exit messages.

## Output contract

A short coach's read (a few sentences) that obeys the voice contract:

- Translate every signal into what it means for the body; never quote the raw number.
- Write to the athlete as "you," in plain language.
- End on one concrete, actionable next step.
- Pass [`voice_violations`](../../coach_voice.py) with zero hits before it ships.

## The athlete model (why a read is "good")

Reads are written against one functional model — speed-dominant engine; limiters are aerobic
durability and weekly volume tolerance, with Achilles risk on high-speed work — detailed in
[`references/coaching_framework.md`](references/coaching_framework.md). A read that ignores
those limiters is describing, not coaching; a clean session is read as clean, with no
manufactured concern.

## Status

- [x] [`derive_signals.py`](../../derive_signals.py) — deterministic
      `stimulus_quality` / `vs_plan` / `key_signal`.
- [x] [`references/coaching_framework.md`](references/coaching_framework.md) — the athlete
      model the read is graded against.
- [x] [`interpret.py`](../../interpret.py) — single-site prompt assembly, the model call,
      the voice-guard retry.
- [x] `ingest/` — intervals.icu activities, plan, laps, and derived metrics.
- [x] `vault/` — bootstrap + the linked-note memory graph.
- [x] [`coach.py`](../../coach.py) — the orchestrator wiring all of the above end to end.
- [x] [`evals/`](../../evals/) — golden set + LLM judge gating the read's quality.
- [ ] Strava / Coros MCP enrichment for deeper per-session analysis *(next)*.

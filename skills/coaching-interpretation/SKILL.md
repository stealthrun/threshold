---
name: coaching-interpretation
description: Coach-style read of one endurance run — pulls it from intervals.icu, interprets it against the athlete's plan, block, and recent weeks, and writes what it meant plus one next step into their Obsidian vault.
---

# coaching-interpretation

> **Status: live, end to end.** Fetches from intervals.icu, interprets against the athlete
> model, and records the read into the vault. The output contract is enforced — see
> [`scripts/coach_voice.py`](scripts/coach_voice.py).

## What this skill does

Turns one training session into a coach's read: what the session *meant for the body*, in
the context of the athlete's recent weeks, training block, and known limiters, ending on a
single concrete next step. It is the opposite of a data dump — it never recites zones or
percentages back at the athlete. The read is saved as a linked note in the athlete's
Obsidian vault, so coaching compounds over time.

## Prerequisites

- **Python 3** (standard library only — nothing to `pip install`).
- **The `claude` CLI** on `PATH` — the read is generated through it. Any Claude Code user
  already has it.
- **intervals.icu credentials** in the environment (the API key is a secret; it is read only
  from the environment, never logged or written to the vault):

      export INTERVALS_ATHLETE_ID=i12345
      export INTERVALS_API_KEY=...        # Settings → Developer on intervals.icu

- **A vault path** — any folder Obsidian opens (it can be empty). The skill creates a
  `threshold/` namespace inside it on first run, non-destructively.

## How to run it

All paths are relative to this skill's folder; the entry point is
[`scripts/coach.py`](scripts/coach.py):

    python3 scripts/coach.py --vault ~/ObsidianVault                  # most recent run
    python3 scripts/coach.py --vault ~/ObsidianVault --activity i123  # a specific activity
    python3 scripts/coach.py --vault ~/ObsidianVault --date 2026-06-18

**Pass the block when the athlete tells you about it.** The training block is the deepest
context tier and the one thing that can't be fetched — it's human-curated intent (what the
plan is *trying* to do right now), and it flips how an identical session reads: an
under-target effort deep in a heavy build is expected fatigue; the same miss in a taper is a
flag. Ask the athlete where they are, then thread it through:

    python3 scripts/coach.py --vault ~/ObsidianVault \
        --block-name "base build" --block-phase build \
        --block-week 6 --block-total-weeks 8 \
        --block-focus "raising weekly volume and aerobic durability"

Once curated, the block also lives in the vault under `threshold/blocks/` — read it there to
recall it on later runs.

## What happens, end to end

`scripts/coach.py` sequences the three layers (see the repo's `docs/ARCHITECTURE.md`); each
step lives in its own module and this is the only place they're wired:

1. **Bootstrap the vault** ([`scripts/vault/bootstrap.py`](scripts/vault/bootstrap.py)) — lay
   down the `threshold/` skeleton + hub notes if missing. Idempotent, never overwrites.
2. **Fetch recent weeks** ([`scripts/ingest/intervals_plan.py`](scripts/ingest/intervals_plan.py))
   — the last few weeks of runs with planned targets attached, plus the recent-week trend,
   in one round trip.
3. **Load the focal session's detail** ([`scripts/ingest/intervals_icu.py`](scripts/ingest/intervals_icu.py))
   — its per-rep work laps, then the derived metrics (pacing consistency, decoupling) folded
   back in so the signals can read them.
4. **Interpret** ([`scripts/interpret.py`](scripts/interpret.py)) — derive the deterministic
   signals (`stimulus_quality`, `vs_plan`, `key_signal`), assemble one prompt from the
   framework + voice contract + session + block + trend, generate the read, and self-correct
   once if the voice guard catches a leak. *This is the only step that needs judgment.*
5. **Record** ([`scripts/vault/notes.py`](scripts/vault/notes.py)) — write the read as a
   linked activity note (wired to its week, block, type, and most similar past sessions),
   preserving anything the athlete wrote under `## Notes`.

If credentials are missing or the `claude` CLI is unavailable, the skill says so plainly and
records nothing rather than failing — see `scripts/coach.py`'s exit messages.

## Output contract

A short coach's read (a few sentences) that obeys the voice contract:

- Translate every signal into what it means for the body; never quote the raw number.
- Write to the athlete as "you," in plain language.
- End on one concrete, actionable next step.
- Pass `voice_violations` ([`scripts/coach_voice.py`](scripts/coach_voice.py)) with zero hits
  before it ships.

## The athlete model (why a read is "good")

Reads are written against one functional model — speed-dominant engine; limiters are aerobic
durability and weekly volume tolerance, with Achilles risk on high-speed work — detailed in
[`references/coaching_framework.md`](references/coaching_framework.md). A read that ignores
those limiters is describing, not coaching; a clean session is read as clean, with no
manufactured concern.

## Installing this skill

This folder is self-contained. To make it available in Claude Code, place it (or a symlink
to it) in your personal skills directory:

    ln -s "$PWD/skills/coaching-interpretation" ~/.claude/skills/coaching-interpretation

The repo's `install.sh` does this for you and prints the env-var setup. Quality is held to
the source repo's `evals/` golden set (runner + LLM judge); those tests aren't shipped with
the installed skill.

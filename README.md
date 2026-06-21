# threshold

I train mostly solo, and every running app I've used does the same thing: it hands me
charts, splits, and a zone pie-graph, then leaves me to figure out what any of it actually
*meant*. A coach never does that. They look at the same numbers and tell you what your
body did, why, and what to do next.

So I built that. **`threshold` reads a training session the way a coach does — not an
analyst.** It's an LLM coaching engine packaged as a
[Claude Agent Skill](skills/coaching-interpretation/), built on my own running data.

The running is just the domain. The real point of this repo is the harder problem
underneath it: **how do you ship an LLM feature you can actually trust?**

## What's in here right now

This is the public, distilled core of a larger private system (`srlOS`, where the full
FIT-file pipeline lives). I'm building it out in the open, one phase at a time:

- ✅ **Voice guard** — `python3 skills/coaching-interpretation/scripts/coach_voice.py`
  (no dependencies)
- ✅ **Design notes + eval methodology** — [`docs/DESIGN.md`](docs/DESIGN.md)
- ✅ **The skill** — signal derivation + interpretation prompt, packaged as an installable
  [Claude Code skill](skills/coaching-interpretation/) (intervals.icu ingestion + Obsidian
  vault memory, wired end to end)
- ✅ **The eval harness**, wired end-to-end — [`evals/`](evals/)

Nothing here claims to do more than those checkboxes. That's deliberate.

## The interesting part (for engineers)

Four ideas do most of the work. None of them are "call the API and hope."

**Evals before prompts.** LLM features fail quietly: they read fine until you tweak a
prompt and something silently regresses. So before writing the prompt I wanted to ship, I
froze the hard cases — eight **golden sessions**, each isolating one read (pace faded but
the heart never maxed; an easy run that crept into tempo; fatigue hiding under on-target
splits). Each one spells out what a good read *must* say and what it must *never* say.
After that, every prompt change is a measured delta, not a vibe. → [`evals/`](evals/)

**Never let the model say the number.** The one rule every prompt obeys: translate the
signal, don't quote it. "You spent 38% in Z5, pacing consistency 0.78" isn't coaching,
it's a data dump — and it's what most tools produce. The forbidden vocabulary is enforced
twice: in the prompt, and by a regex on the model's *output*
([`coach_voice.py`](skills/coaching-interpretation/scripts/coach_voice.py)), in one file so the rule and its checker can't drift
apart. A prompt can *ask* for clean prose; this *proves* it.

**Use the model only where you have to.** Whether a session hit its target, whether it was
quality, the one-line summary of what happened — that's plain Python. Testable, free,
deterministic. The model only does the irreducibly fuzzy part: turning those signals into
a coach's read. Keep the surface where it can hallucinate small.

**One engine, not a committee of agents.** It's tempting to build a "panel" — a fatigue
agent, a pacing agent, a coordinator — because it demos well. I didn't. One engine holding
the full context gives a more coherent read and is far easier to evaluate. The boring
architecture was the right one.

## Describe vs. interpret

Same session, two ways of talking about it:

> **Analyst** (most tools): "Z5 time 38%, pacing consistency 0.78, decoupling in rep 4 —
> classic VO2 fade."

> **Coach** (`threshold`): "Your legs hit their limit before your heart did. The pace bled
> away while your effort stayed under the ceiling, so the cardiovascular stimulus was
> diminished, not a bad day. Next time, drop a rep and hold the pace."

Both are true. Only one tells you what happened and what to do. Full walk-through in
[`examples/faded_vo2.md`](examples/faded_vo2.md).

## Run the part that runs

```bash
python3 skills/coaching-interpretation/scripts/coach_voice.py
```

Scans a deliberately messy analyst brief and a clean coach brief, and prints exactly which
rule each one trips. No install, standard library only.

## Install it as a skill

The interpretation engine is packaged as a self-contained
[Claude Code skill](skills/coaching-interpretation/). Install it (symlink by default), set
your intervals.icu credentials, and ask Claude about your training:

```bash
./install.sh                                  # links it into ~/.claude/skills/
export INTERVALS_ATHLETE_ID=i12345
export INTERVALS_API_KEY=...                  # Settings → Developer on intervals.icu
```

Then, in Claude Code: *"how did my last run go?"* — or run it directly with
`python3 skills/coaching-interpretation/scripts/coach.py --vault ~/ObsidianVault`. It needs
the `claude` CLI on your PATH and Python 3; no other dependencies.

## License

MIT — see [LICENSE](LICENSE).

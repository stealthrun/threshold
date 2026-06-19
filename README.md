# threshold

**Most training tools describe your data. `threshold` interprets it.**

An eval-backed, agent-native coaching engine. Give it a training session and it reads
that session the way a coach does — not an analyst. It tells you what the session *meant
for your body* and what to do next, instead of reciting heart-rate zones and percentages
back at you.

It's packaged as a [Claude Agent Skill](skills/coaching-interpretation/), and it's built
on a real, personal dataset: my own running. The interesting part isn't the running —
it's the engineering discipline around making an LLM coach *reliably*.

---

## The one insight

Every endurance tool on the market shows you the same thing: charts, splits, zone
pie-graphs. None of them tell you what a session actually *meant*. The gap was never
data — it's interpretation. A coach doesn't read you your numbers; they read what the
numbers imply about your body, in the context of your last six weeks. `threshold` is an
attempt to encode that read.

## What's interesting here (for engineers)

This is a study in shipping an LLM feature you can *trust* — not a chatbot demo.

### 1. Evals before prompts
Before touching a single prompt, the hard cases are frozen as **golden sessions**: eight
scenarios that each isolate one coaching read — a VO2 set where the pace faded but the
heart never maxed, an easy run that drifted into tempo, fatigue hiding under on-target
splits. Each golden carries a `must_address` list (what a good read has to engage) and a
`must_not` list (what it must never do — e.g. *manufacture concern a clean session
doesn't warrant*). Every prompt change after that is a **measured delta against the
goldens, not a vibe.** → [`evals/`](evals/)

### 2. A two-layer gate: deterministic + judge
- **Voice guard** — a free, instant regex that scans the model's *output* for leaked
  zone codes, percentages, internal scores, and analyst jargon. The half a prompt can't
  guarantee. Runnable today. → [`coach_voice.py`](coach_voice.py)
- **LLM judge** — a separate model call grading whether the brief actually *coached*: did
  it engage the core signal, read as a coach not an analyst, ground its claims in the
  data, and end on a concrete action.

A golden passes only if the guard is clean **and** the judge passes every criterion. The
gate is deliberately hard to please.

### 3. Deterministic where it should be, LLM where it has to be
The signals (`stimulus_quality`, `vs_plan`, `key_signal`) are derived in plain, testable
Python — verifiable and free. The LLM only does the part that genuinely needs judgment:
turning those signals into a coach's read. Knowing which half is which is most of the job.

### 4. One tooled engine, not a multi-agent panel
The coach is a single engine holding the athlete's context — not a swarm of role-played
"specialist agents." That restraint is a design decision: the simpler correct
architecture beats the impressive-looking one.

---

## The voice contract (a concrete example)

The single rule every prompt obeys: **translate the signal, never quote the number.**

> **Analyst (what most tools produce):**
> "Z5 time was 38%, pacing consistency 0.78, clear decoupling in rep 4 — classic VO2 fade."

> **Coach (what `threshold` produces):**
> "Your legs hit their limit before your heart did. The pace bled away while your effort
> stayed under the ceiling, so the cardiovascular stimulus was diminished, not a bad day.
> Next time drop a rep and hold the pace."

The forbidden vocabulary is enforced both in the prompt (`VOICE_GUARDRAILS`) and on the
output (`voice_violations`) — in one module, so the rule and its checker can't drift.

## Run the part that runs today

No dependencies. Pure standard library.

```bash
python coach_voice.py
```

It scans a deliberately "dirty" analyst brief and a clean coach brief, and prints exactly
which rule each one trips.

## Status

Assembled in the open as a portfolio piece. Honest state:

- [x] Voice contract + deterministic voice guard — **runnable**
- [x] Golden-session methodology + eval design — see [`evals/`](evals/)
- [x] A worked before/after example — see [`examples/`](examples/)
- [ ] Skill packaging (`SKILL.md` prompt + helper scripts) — *Phase 2*
- [ ] Eval harness wired to the live generator (judge + runner) — *Phase 3*

The full reasoning engine and its FIT-file data pipeline live in a separate private lab
(`srlOS`). This repo is the distilled, legible core — the parts worth reading.

## License
MIT — see [LICENSE](LICENSE).

# Architecture

[`DESIGN.md`](DESIGN.md) explains *why the read is built the way it is*. This document
explains *how the read sits inside a larger coaching system* — the layers around the
engine, and the rule that keeps the trustworthy core from being diluted as that system
grows.

## The problem this layering solves

`threshold`'s value is that it interprets a session **in context** — not in isolation. An
under-target threshold rep means one thing in a build week and the opposite in a taper; a
cut session is a failure or a smart back-off depending on the block. So the engine needs
*data* (the workouts) and *memory* (the history, the block, prior reads) around it.

The temptation is to fuse all of that into one big skill: auth, API calls, vault
management, and interpretation in a single blob. That would destroy the one thing that
makes the read trustworthy — the focused, eval-backed, voice-guarded core. So the system is
**three layers with dependencies pointing inward**: the core knows nothing about where data
comes from or where context is stored.

```
            ┌─────────────────────────────────────────────┐
   Layer 3  │  ENRICHMENT TOOLS  (later — MCP)             │
            │  Strava / Coros / Garmin MCP servers         │
            │  deeper per-session detail on demand         │
            └───────────────────┬─────────────────────────┘
                                 │ feed richer facts
            ┌────────────────────▼────────────────────────┐
   Layer 2  │  ORCHESTRATION & CONTEXT  (the coaching skill)│
            │  fetch · assemble context · memory (vault) ·  │
            │  persist the read · speak in voice            │
            └────────────────────┬────────────────────────┘
                                 │ context in → read out
            ┌────────────────────▼────────────────────────┐
   Layer 1  │  REASONING CORE  (threshold)                  │
            │  derive_signals · interpret · framework ·     │
            │  voice guard · evals                          │
            │  PURE: no I/O, no network, no knowledge of    │
            │  intervals.icu, vaults, or MCP                │
            └─────────────────────────────────────────────┘

   Dependencies point inward. The core depends on nothing above it.
```

## Layer 1 — the reasoning core (`threshold`)

The part that exists today and stays exactly as it is.

- **Owns:** the deterministic signals ([`derive_signals.py`](../derive_signals.py)), the
  interpretation step ([`interpret.py`](../interpret.py)), the athlete model
  ([`coaching_framework.md`](../skills/coaching-interpretation/references/coaching_framework.md)),
  the voice contract + guard ([`coach_voice.py`](../coach_voice.py)), and the quality gate
  ([`evals/`](../evals/)).
- **Contract:** context in, read out. `interpret(session, recent_weeks)` is a pure
  function of its inputs — it makes one model call to write the prose, but it fetches
  nothing and stores nothing.
- **Must not:** know about intervals.icu, OAuth, vaults, file paths, or MCP. The moment the
  core imports a data source, it stops being independently testable, and the eval harness
  stops measuring a fixed thing.

This purity is *why* the evals work: the harness scores one fixed code path. Everything
that would make that path non-deterministic lives in the layers above.

## Layer 2 — orchestration & context (the coaching skill)

The layer that turns the core into something a real athlete can use. This is the
`SKILL.md` orchestrator plus its bundled scripts.

- **Owns:**
  - **Fetch** — pull the last *N* weeks of activities (and the plan) from a data source.
    The first source is the intervals.icu REST API; the shape it produces is the `session`
    dict the core already consumes.
  - **Context assembly** — turn raw activities into `recent_weeks`, look up the current
    **block** and prior reads from the vault, and hand the core a fully-contextualised
    input.
  - **Memory** — the Obsidian vault is the store. The skill reads context from it and
    writes each new read back, so today's interpretation becomes tomorrow's context.
  - **Auth** — see [Credentials](#credentials-intervalsicu) below.
  - **Speak** — surface the core's read to the athlete (already voice-guarded).
- **Must not:** reimplement interpretation, or emit athlete-facing prose that bypasses the
  voice guard. The reasoning stays in Layer 1; this layer only feeds and persists it.

### Context tiers

"In context" means three tiers, supplied differently:

| tier | what it is | where it comes from |
|---|---|---|
| **session facts** | this workout's data + per-rep laps | the data source (intervals.icu / MCP) |
| **recent weeks** | trailing load and fatigue (2–4 weeks) | derived from fetched activities — *already in the core's contract* |
| **block / periodization** | where you are in the plan (build / sharpen / taper) | **human-curated**, persisted in the vault |

Blocks are deliberately **human-supplied**, not auto-derived: periodization is *intent*,
not something measurable from activity data. The athlete tells the agent ("I'm in a
competition block, week 5 of 8"), it's written to the vault, and from then on every read
is interpreted against it.

### The vault contract (memory)

One rule, carried over from the private lab: **the agent owns the structured part, the
human owns the prose.** The skill may create and update the machine-readable fields and the
generated read; it must **never** overwrite the athlete's own free-text notes. Writes are
**idempotent** — re-running "read my last 4 weeks" must not duplicate notes or clobber
hand-written observations.

### Credentials (intervals.icu)

**Now (local skill): a personal API key.** A skill is code running on the athlete's own
machine — there is no server in the loop. intervals.icu uses Basic auth with a personal API
key the athlete generates in their own settings; the skill reads it from an environment
variable or a gitignored local config and never writes it to the vault or logs it. Nothing
sensitive is embedded in the distributed skill, and the athlete can revoke the key
themselves.

**Later (hosted product): OAuth.** When threshold becomes a hosted, multi-tenant service,
OAuth is correct — a backend you control holds the client secret and stores per-user tokens
server-side, with scoped access and revocation. (Confidential-client OAuth needs a client
secret that a *distributed* skill cannot keep, which is exactly why it is wrong for the
local phase and right for the hosted one.)

**The seam:** auth hides behind a small credentials provider, so the fetch layer only asks
for "a valid token" and does not care whether it came from a local API key or a hosted
OAuth backend. Moving from one to the other is a one-file change.

*Caveat:* intervals.icu API keys are account-wide (no fine-grained read-only scope), so the
key is sensitive and treated accordingly.

## Layer 3 — enrichment tools (later, MCP)

Additive, optional capability. MCP servers for Strava, Coros, Garmin, etc. let the agent go
**deeper on a single session** — pull richer streams, photos, segment detail — than the
primary fetch provides. They plug into the same place the fetch layer feeds: richer facts
into the `session` dict the core consumes. They enrich the *input*; they never touch the
interpretation. Nothing in Layers 1–2 depends on them, so they can land whenever, one at a
time.

## The testability boundary

The split is also a testing strategy:

- **Layer 1 is eval-gated.** Deterministic unit tests + the golden harness, exactly as
  today. It stays pure, so what's measured is what ships.
- **Layers 2–3 are smoke-tested**, not held to goldens. Once an agent orchestrates
  fetch + vault + interpret with tool calls, the "thing under test" is larger and less
  deterministic. That is fine — but it is kept *outside* the core so the agentic
  flexibility never infects the core's determinism.

The discipline in one line: **let the orchestration be agentic and fuzzy; keep the
reasoning deterministic and gated.**

## Status

- ✅ **Layer 1** — built: signals, interpretation, framework, voice guard, evals.
- 🚧 **Layer 2** — next: block context in the core's contract, then intervals.icu fetch,
  then the vault memory layer, then the `SKILL.md` orchestrator.
- ⏳ **Layer 3** — later: Strava / Coros / Garmin MCP enrichment.

The build order is deliberate: the contextual-coaching claim is proven *in the core first*
(block context + a golden showing the same session read differently across blocks), with no
external dependency, before any integration work begins.

# Layer 2 (orchestration & context) — data ingestion.
#
# This package is the data seam described in docs/ARCHITECTURE.md: it turns an external
# source (intervals.icu today; Strava/Coros via MCP later) into the `session` dicts the
# reasoning core consumes. The core (derive_signals, interpret, coach_voice) depends on
# nothing in here — the dependency points inward, never out.

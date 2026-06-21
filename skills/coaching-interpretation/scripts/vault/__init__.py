# Layer 2 (orchestration & context) — the vault memory layer.
#
# The Obsidian vault is threshold's memory: it persists the athlete's history, blocks, and
# past reads so the engine coaches in context and compounds over time (see
# docs/ARCHITECTURE.md). This package bootstraps that vault and, later, reads/writes the
# wikilink graph the agent navigates by. The reasoning core depends on nothing in here.

"""
Bootstrap the Obsidian vault that is threshold's memory layer.

The vault is the retrieval layer, not a folder of notes (see docs/ARCHITECTURE.md). Before
anything can be read *from* it, the structure has to exist — and the athlete may have an
empty vault, no vault, or an existing personal one this must not trample. So bootstrap is:

  idempotent     run it twice, no harm; it creates only what is missing and never
                 overwrites an existing note (the athlete's own prose is sacred);
  non-invasive   everything lives under a `threshold/` namespace inside the vault, never
                 dumped into the root of someone's existing notes;
  self-scaffolding  it lays down the folder skeleton plus seed hub notes (the session-type
                 hubs and the athlete profile), so the wikilink graph always has anchors
                 for the first activity note to link into.

This is Step 3a. Writing the activity / week / block notes and their `## Links` (the graph
itself) is Step 3b — this only guarantees the ground they link into exists.

Distilled from the lab's setup_vault.py, trimmed to the public structure and stdlib only.

    python3 -m vault.bootstrap /path/to/ObsidianVault
"""

from __future__ import annotations

from pathlib import Path

# Everything threshold writes lives under this one folder inside the athlete's vault.
NAMESPACE = "threshold"

# The folder skeleton. Each holds one kind of note; activity/week/block notes are written
# by Step 3b, but the directories (and the hubs they link to) must exist first.
SUBDIRS = ("activities", "weeks", "blocks", "types")

# The session-type hubs — one note per taxonomy type (matching derive_signals.py). They
# exist so every activity of a type can backlink to its hub, making "show me all my VO2
# sessions" a one-hop graph traversal instead of a scan.
TYPE_HUBS: dict[str, str] = {
    "jog": "Recovery-pace running. Very easy and short — a shake-out, not training.",
    "easy": "Conversational aerobic running. The base; it must stay genuinely easy.",
    "long": "Sustained aerobic running. Trains durability — the real limiter.",
    "tempo": "Sustained, comfortably hard continuous effort.",
    "threshold": "Repeated efforts at lactate threshold. Structured quality work.",
    "vo2": "High-intensity intervals near maximum aerobic power.",
}


# ── Note bodies ───────────────────────────────────────────────────────────────────────

def _type_hub_note(name: str, description: str) -> str:
    """A hub note: a heading, the one-line meaning, and a tag the graph can colour. Every
    session of this type will backlink here automatically (Obsidian backlinks)."""
    return (
        f"# {name}\n\n"
        f"{description}\n\n"
        f"#{name}\n\n"
        f"## Sessions\n"
        f"<!-- Sessions of this type link here; Obsidian shows them under Backlinks. -->\n"
    )


def _profile_note() -> str:
    """The athlete model the reads are written against — the functional traits only. Seeded
    here so the agent has a profile to read; the athlete is meant to edit and grow it."""
    return (
        "# Athlete profile\n\n"
        "The functional model threshold coaches against. Edit freely — what you write "
        "here becomes context for every read.\n\n"
        "## Engine\n"
        "Speed-dominant (short-to-middle-distance background). Strong leg speed and "
        "economy; high tolerance for intensity. Not a big aerobic engine — the top end is "
        "a relative strength, not the bottleneck.\n\n"
        "## Limiters\n"
        "- Aerobic durability — the real bottleneck; easy runs must stay easy.\n"
        "- Weekly volume tolerance — fatigue accrues near the top of the range.\n"
        "- Achilles risk on high-speed work — back off early, it is never noise.\n\n"
        "## Notes\n"
        "<!-- Your own observations. threshold never overwrites this section. -->\n"
    )


def _index_note() -> str:
    """The vault entry note — explains the structure to a human opening the vault."""
    return (
        "# threshold\n\n"
        "This folder is threshold's memory. The coaching engine reads context from here "
        "and writes each session's read back, so coaching compounds over time.\n\n"
        "- `activities/` — one note per session\n"
        "- `weeks/` — weekly rollups\n"
        "- `blocks/` — your training blocks (you curate these)\n"
        "- `types/` — a hub per session type; every session links to its hub\n"
        "- `profile.md` — the athlete model, yours to edit\n"
    )


# ── Bootstrap ─────────────────────────────────────────────────────────────────────────

def _write_if_missing(path: Path, content: str) -> bool:
    """Write the note only if it does not already exist. Returns True if it created the
    file. This is the never-overwrite rule — an existing note (and the athlete's edits in
    it) is always left untouched."""
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def bootstrap_vault(vault_path: str | Path) -> dict:
    """Lay down the threshold namespace inside `vault_path`: the folder skeleton, the
    session-type hubs, the profile, and the index. Idempotent and non-invasive — only the
    `threshold/` subtree is touched, and nothing existing is overwritten.

    Returns a report: {"root", "created": [...], "existing": [...]} of note paths relative
    to the namespace root.
    """
    base = Path(vault_path).expanduser()
    if base.exists() and not base.is_dir():
        raise NotADirectoryError(f"vault path is not a directory: {base}")

    root = base / NAMESPACE
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    existing: list[str] = []

    def _record(path: Path, content: str) -> None:
        (created if _write_if_missing(path, content) else existing).append(
            str(path.relative_to(root))
        )

    for name, desc in TYPE_HUBS.items():
        _record(root / "types" / f"{name}.md", _type_hub_note(name, desc))
    _record(root / "profile.md", _profile_note())
    _record(root / "index.md", _index_note())

    return {"root": str(root), "created": created, "existing": existing}


# ── CLI ───────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python3 -m vault.bootstrap /path/to/ObsidianVault")
        raise SystemExit(2)

    report = bootstrap_vault(sys.argv[1])
    print(f"vault ready at {report['root']}")
    if report["created"]:
        print(f"  created {len(report['created'])}: {', '.join(report['created'])}")
    if report["existing"]:
        print(f"  kept {len(report['existing'])} existing: {', '.join(report['existing'])}")
    if not report["created"]:
        print("  (nothing to do — already bootstrapped)")

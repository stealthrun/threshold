"""
Write sessions into the vault as linked notes — the wikilink graph that turns the vault
from a folder into a navigable memory (Step 3b; see docs/ARCHITECTURE.md).

Each session becomes one activity note carrying, in the dual-audience shape the lab uses:
a YAML frontmatter (for filtering), the coach's read (the human-facing body), a JSON
details block (machine-readable signals + facts), a `## Links` section, and a `## Notes`
section the athlete owns. The links are the index: an activity points at its week, its
block, its session-type hub, and the most similar past sessions, so "where am I in the
block?" and "how does this compare to past threshold work?" are graph hops, not scans. A
new note links itself in, so the memory compounds.

Two rules carried from the bootstrap (and the lab): the agent owns the structured fields,
the links, and the read; it **never** overwrites the athlete's `## Notes`, and re-recording
a session updates its note in place (stable name by source id) while preserving those
notes.

Distilled from the lab's link_graph.py (similarity) and generate_md.py (note shape), on
the public session contract and stdlib only.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from derive_signals import derive_signals
from vault.bootstrap import NAMESPACE

# Similarity (distilled from link_graph.py): same type, scored on distance / pace / HR.
_TOP_N = 3
_MIN_SCORE = 0.5
_SIM_TOLERANCE = {"distance_km": 0.30, "avg_pace_sec_per_km": 0.15, "avg_hr": 0.10}


# ── Naming ────────────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def week_key(iso_date: str) -> str | None:
    """An ISO date → its week note name, e.g. '2026-06-15' -> '2026-W25'."""
    try:
        y, w, _ = date.fromisoformat(iso_date).isocalendar()
    except (ValueError, TypeError):
        return None
    return f"{y}-W{w:02d}"


def activity_basename(session: dict) -> str:
    """A stable note name per session, so re-recording updates the same note. Keyed on the
    source id when present (the only truly stable handle), else date + type."""
    d = (session.get("date") or "undated")
    t = session.get("activity_type") or "session"
    sid = session.get("source_id")
    return f"{d}_{t}_{sid}" if sid else f"{d}_{t}"


# ── Frontmatter + section helpers (parse only the simple notes we write) ───────────────

def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm: dict = {}
    for line in text[3:end].strip().splitlines():
        key, sep, val = line.partition(":")
        if sep:
            fm[key.strip()] = val.strip()
    return fm


def _as_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _extract_notes_section(text: str) -> str | None:
    """Return the athlete's `## Notes` body from an existing note, so a rewrite preserves
    it. None when the note doesn't exist or has no such section."""
    m = re.search(r"\n## Notes\n(.*)\Z", text, re.S)
    return m.group(1).rstrip("\n") if m else None


# ── Similarity (same-type past sessions) ──────────────────────────────────────────────

def _numeric_similarity(a: float | None, b: float | None, tol: float) -> float | None:
    if a is None or b is None:
        return None
    ref = max(abs(a), abs(b))
    if ref == 0:
        return 1.0
    return max(0.0, 1.0 - (abs(a - b) / ref) / tol)


def find_similar(activities_dir: Path, session: dict, top_n: int = _TOP_N) -> list[str]:
    """Scan written activity notes and return the basenames of the most similar past
    sessions of the SAME type (distance / pace / HR), best first. The 'have I done this
    before?' backlink."""
    wtype = session.get("activity_type")
    if not wtype or not activities_dir.is_dir():
        return []
    self_name = activity_basename(session)

    scored: list[tuple[float, str]] = []
    for md in activities_dir.glob("*.md"):
        if md.stem == self_name:
            continue
        fm = _parse_frontmatter(md.read_text(encoding="utf-8"))
        if fm.get("type") != wtype:
            continue
        parts = [
            _numeric_similarity(_as_float(session.get(field)), _as_float(fm.get(field)), tol)
            for field, tol in _SIM_TOLERANCE.items()
        ]
        valid = [p for p in parts if p is not None]
        if not valid:
            continue
        score = sum(valid) / len(valid)
        if score >= _MIN_SCORE:
            scored.append((score, md.stem))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [name for _, name in scored[:top_n]]


# ── Rendering ─────────────────────────────────────────────────────────────────────────

def _frontmatter(session: dict, signals: dict) -> str:
    fields = {
        "date": session.get("date"),
        "type": session.get("activity_type"),
        "distance_km": session.get("distance_km"),
        "avg_pace_sec_per_km": session.get("avg_pace_sec_per_km"),
        "avg_hr": session.get("avg_hr"),
        "stimulus_quality": signals.get("stimulus_quality"),
        "vs_plan": signals.get("vs_plan"),
        "source_id": session.get("source_id"),
    }
    lines = [f"{k}: {v}" for k, v in fields.items() if v is not None]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _details_block(session: dict, signals: dict) -> str:
    detail = {
        "source_id": session.get("source_id"),
        "type": session.get("activity_type"),
        "distance_km": session.get("distance_km"),
        "avg_pace_sec_per_km": session.get("avg_pace_sec_per_km"),
        "avg_hr": session.get("avg_hr"),
        "max_hr": session.get("max_hr"),
        **signals,
    }
    return "## Details\n```json\n" + json.dumps(detail, indent=2) + "\n```\n"


def _fmt_pace(sec_per_km) -> str:
    if not sec_per_km:
        return "—"
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def _splits_block(laps: list[dict] | None) -> str:
    """A per-lap table (pace / HR / zone) so the splits the read is built on are visible in
    the note, not just folded into signals. Empty string when there are no laps."""
    rows = [l for l in (laps or []) if l.get("avg_pace_sec_per_km") or l.get("avg_hr")]
    if not rows:
        return ""
    out = ["## Splits", "", "| # | type | dist | pace | HR | zone |",
           "|--:|------|-----:|------|---:|---:|"]
    for i, l in enumerate(rows, 1):
        dist = f"{l['distance_m'] / 1000:.2f}km" if l.get("distance_m") else "—"
        zone = l.get("zone")
        out.append(
            f"| {i} | {l.get('lap_type', '')} | {dist} | "
            f"{_fmt_pace(l.get('avg_pace_sec_per_km'))} | {l.get('avg_hr') or '—'} | "
            f"{zone if zone is not None else '—'} |"
        )
    return "\n".join(out) + "\n"


def _links_block(week: str | None, block: str | None, type_name: str | None,
                 similar: list[str]) -> str:
    lines = ["## Links"]
    if week:
        lines.append(f"- Week: [[{week}]]")
    if block:
        lines.append(f"- Block: [[{_slug(block)}]]")
    if type_name:
        lines.append(f"- Type: [[{type_name}]]")
    if similar:
        lines.append("- Similar: " + ", ".join(f"[[{name}]]" for name in similar))
    return "\n".join(lines) + "\n"


def render_activity_note(session: dict, read: str, *, week: str | None,
                         block: str | None, similar: list[str],
                         preserved_notes: str | None = None) -> str:
    """Render one activity note: frontmatter, the key-signal callout, the coach's read,
    the JSON details, the links, and the athlete's preserved (or seeded) notes."""
    signals = derive_signals(session)
    notes = preserved_notes if preserved_notes is not None else (
        "<!-- Your own observations. threshold never overwrites this section. -->"
    )
    title = f"{session.get('date', '')} — {session.get('activity_type', 'session')}".strip(" —")
    splits = _splits_block(session.get("laps"))
    return (
        f"{_frontmatter(session, signals)}\n"
        f"# {title}\n\n"
        f"> {signals.get('key_signal', '')}\n\n"
        f"{read.strip()}\n\n"
        f"{_details_block(session, signals)}\n"
        f"{splits + chr(10) if splits else ''}"
        f"{_links_block(week, block, session.get('activity_type'), similar)}\n"
        f"## Notes\n{notes}\n"
    )


# ── Writing ───────────────────────────────────────────────────────────────────────────

def _write_block_stub(blocks_dir: Path, block: str) -> None:
    """Create a placeholder note for a referenced block if it doesn't exist, so the link
    resolves. Never overwrites — the athlete curates the block's real content."""
    path = blocks_dir / f"{_slug(block)}.md"
    if not path.exists():
        path.write_text(
            f"# {block}\n\n## Focus\n\n## Notes\n"
            "<!-- Curate this block: its phase, goal, and weeks. -->\n",
            encoding="utf-8",
        )


def _ensure_week_note(weeks_dir: Path, week: str, block: str | None) -> None:
    """Ensure the week note exists (so the activity's week link resolves) and links up to
    its block. Never overwrites an existing week note."""
    path = weeks_dir / f"{week}.md"
    if path.exists():
        return
    body = f"# {week}\n\n"
    if block:
        body += f"## Links\n- Block: [[{_slug(block)}]]\n\n"
    body += "## Notes\n<!-- Week rollup. -->\n"
    path.write_text(body, encoding="utf-8")


def record_session(vault_path: str | Path, session: dict, read: str,
                   block: str | None = None) -> Path:
    """Persist one session's read into the vault as a linked activity note, wiring it into
    the graph (week / block / type / similar). Idempotent on the session's stable name and
    non-destructive: an existing note's `## Notes` is preserved across the rewrite.

    Returns the path to the activity note. Assumes the vault is bootstrapped; creates the
    needed directories defensively.
    """
    root = Path(vault_path).expanduser() / NAMESPACE
    activities_dir = root / "activities"
    for sub in ("activities", "weeks", "blocks"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    name = activity_basename(session)
    note_path = activities_dir / f"{name}.md"
    preserved = (_extract_notes_section(note_path.read_text(encoding="utf-8"))
                 if note_path.exists() else None)

    week = week_key(session.get("date") or "")
    similar = find_similar(activities_dir, session)

    note_path.write_text(
        render_activity_note(session, read, week=week, block=block, similar=similar,
                             preserved_notes=preserved),
        encoding="utf-8",
    )

    if week:
        _ensure_week_note(root / "weeks", week, block)
    if block:
        _write_block_stub(root / "blocks", block)

    return note_path


def is_recorded(vault_path: str | Path, session: dict) -> bool:
    """True if this session already has an activity note (by its stable name). Lets a bulk
    sync skip sessions already read instead of re-spending a model call on them."""
    activities = Path(vault_path).expanduser() / NAMESPACE / "activities"
    return (activities / f"{activity_basename(session)}.md").is_file()

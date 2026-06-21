"""
The orchestrator — the one entry point that turns "read my latest run" into a coach's read
saved to the vault. It wires the three layers (see docs/ARCHITECTURE.md) together, and is
the script the skill runs:

  Layer 2 (ingest)  fetch the last few weeks from intervals.icu (runs + plan), then load
                    the focal session's per-rep laps and derived metrics.
  Layer 1 (core)    interpret that session against the athlete framework, its block, and
                    the recent-week trend — the deterministic signals plus the LLM read,
                    voice-guarded.
  Layer 2 (vault)   bootstrap the vault if needed and record the read as a linked note, so
                    the coaching compounds.

Each step lives in its own module; this file only sequences them and degrades gracefully
(a clear message, never a stack trace) when credentials are missing or the model is
unavailable. The block is the one piece that can't be fetched — it's human-curated intent
(see the framework) — so the caller supplies it; everything else is pulled.

    python3 coach.py --vault ~/ObsidianVault                 # read the most recent run
    python3 coach.py --vault ~/ObsidianVault --activity i123 # read a specific activity
    python3 coach.py --vault ~/ObsidianVault --date 2026-06-18 \
        --block-name "base build" --block-phase build --block-week 6 --block-total-weeks 8
"""

from __future__ import annotations

from pathlib import Path

from ingest.intervals_icu import Credentials, IntervalsError, load_session_detail
from ingest.intervals_plan import fetch_recent_with_plan
from interpret import interpret
from vault.bootstrap import bootstrap_vault
from vault.notes import record_session


# ── Selecting the focal session ────────────────────────────────────────────────────────

def select_session(sessions: list[dict], *, activity_id: str | None = None,
                   date: str | None = None) -> dict | None:
    """Pick the one session to read closely from the fetched window. By source id if given,
    else by date (the most recent run on that day), else the most recent run. Sessions are
    newest-first, so the first match wins."""
    if activity_id:
        return next((s for s in sessions if s.get("source_id") == activity_id), None)
    if date:
        return next((s for s in sessions if s.get("date") == date), None)
    return sessions[0] if sessions else None


def _block_from_args(name, phase, week, total_weeks, focus) -> dict | None:
    """Assemble the block dict from whatever the caller supplied. None when nothing is
    given — the core then reads the session on its own merits (see interpret._fmt_block)."""
    block = {
        "name": name, "phase": phase, "week": week,
        "total_weeks": total_weeks, "focus": focus,
    }
    block = {k: v for k, v in block.items() if v is not None}
    return block or None


# ── The pipeline ───────────────────────────────────────────────────────────────────────

def coach_session(creds: Credentials, vault_path: str | Path, *, weeks: int = 4,
                  activity_id: str | None = None, date: str | None = None,
                  block: dict | None = None) -> dict:
    """Run the end-to-end read for one session and persist it.

    Fetches the trailing `weeks` of runs (with plan targets) and the recent-week trend,
    selects the focal session, loads its laps + derived metrics, interprets it against the
    framework / block / trend, and records the read into the vault.

    Returns a report: {"read", "note_path", "session", "recent_weeks"}. `read`/`note_path`
    are None when there were no sessions, or when the model was unavailable (the caller can
    surface the reason). Raises IntervalsError only for fetch/auth failures.
    """
    bootstrap_vault(vault_path)

    sessions, recent_weeks = fetch_recent_with_plan(creds, weeks=weeks)
    focal = select_session(sessions, activity_id=activity_id, date=date)
    if focal is None:
        return {"read": None, "note_path": None, "session": None,
                "recent_weeks": recent_weeks}

    load_session_detail(creds, focal)               # laps + metrics, folded into `focal`
    read = interpret(focal, recent_weeks, block)
    if not read:
        return {"read": None, "note_path": None, "session": focal,
                "recent_weeks": recent_weeks}

    note_path = record_session(vault_path, focal, read, block)
    return {"read": read, "note_path": note_path, "session": focal,
            "recent_weeks": recent_weeks}


# ── CLI ────────────────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    import argparse

    p = argparse.ArgumentParser(
        description="Interpret one intervals.icu run as a coach and save it to the vault.")
    p.add_argument("--vault", required=True, help="path to the Obsidian vault")
    p.add_argument("--weeks", type=int, default=4, help="weeks of context to fetch (default 4)")
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--activity", help="intervals.icu activity id to read (e.g. i123)")
    sel.add_argument("--date", help="read the run on this date (YYYY-MM-DD)")
    p.add_argument("--block-name", help="the current training block's name")
    p.add_argument("--block-phase", help="base / build / sharpening / taper")
    p.add_argument("--block-week", type=int, help="which week of the block this is")
    p.add_argument("--block-total-weeks", type=int, help="the block's length in weeks")
    p.add_argument("--block-focus", help="what the block is trying to achieve right now")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        creds = Credentials.from_env()
    except IntervalsError as exc:
        print(f"  {exc}")
        print("  Set INTERVALS_ATHLETE_ID and INTERVALS_API_KEY, then re-run.")
        return 2

    block = _block_from_args(args.block_name, args.block_phase, args.block_week,
                             args.block_total_weeks, args.block_focus)

    try:
        report = coach_session(creds, args.vault, weeks=args.weeks,
                               activity_id=args.activity, date=args.date, block=block)
    except IntervalsError as exc:
        print(f"  fetch failed: {exc}")
        return 1

    if report["session"] is None:
        print("  No run found in the fetched window. Try a wider --weeks or check --date/--activity.")
        return 1
    if report["read"] is None:
        print("  Couldn't generate a read (the claude CLI is unavailable). Session fetched but not recorded.")
        return 1

    print(report["read"])
    print(f"\n  saved to {report['note_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Run the eval harness: generate each golden's read with the REAL generator (interpret.py),
score it on both layers of the gate (the deterministic voice guard + the LLM judge), print
a scorecard, and save the run for cross-run diffing.

    python3 -m evals.run                   # all goldens, voice guard + judge
    python3 -m evals.run --no-judge        # deterministic guard only (fast, free)
    python3 -m evals.run --only faded_vo2  # one scenario
    python3 -m evals.run --full            # print the full read text

Each run writes evals/results/<timestamp>.json (gitignored). This is the baseline gate for
the interpretation layer: change the prompt, re-run, read the delta as a number instead of
a vibe. The read is generated through interpret.interpret — the same code path the skill
runs — so the harness scores the real thing, not a reimplementation.

A golden PASSES only if the voice guard is clean AND the judge passes every criterion.
The process exit code is non-zero if any golden fails the gate, so this drops into CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from coach_voice import voice_violations  # noqa: E402
from evals import judge as judge_mod  # noqa: E402
from evals.golden_sessions import GOLDENS, GOLDENS_BY_NAME  # noqa: E402
from interpret import interpret  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m",
)


def _tick(ok: bool) -> str:
    return f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"


def evaluate_one(golden: dict, use_judge: bool) -> dict:
    """Generate + score one golden. Returns a result row (also the saved-JSON shape)."""
    brief = interpret(golden["session"], golden.get("recent_weeks"))
    if not brief:
        return {"name": golden["name"], "error": "no read (claude unavailable or empty)"}

    violations = voice_violations(brief)
    row = {
        "name": golden["name"],
        "brief": brief,
        "voice_clean": not violations,
        "violations": violations,
    }
    if use_judge:
        verdict = judge_mod.judge_brief(golden, brief)
        if verdict is None:
            row["judge_error"] = "judge unavailable or unparseable"
        else:
            row["judge"] = verdict
            row["judge_pass"] = judge_mod.passed(verdict)
    return row


def _print_row(row: dict, show_full: bool) -> None:
    name = row["name"]
    if "error" in row:
        print(f"\n{BOLD}{name}{RESET}  {RED}ERROR{RESET} — {row['error']}")
        return

    voice_ok = row["voice_clean"]
    judge = row.get("judge")
    judge_pass = row.get("judge_pass")

    overall = voice_ok and (judge is None or judge_pass)
    header = f"{GREEN}PASS{RESET}" if overall else f"{RED}FAIL{RESET}"
    if "judge_error" in row and voice_ok:
        header = f"{YELLOW}PARTIAL{RESET}"
    print(f"\n{BOLD}{name}{RESET}  {header}")

    brief = row["brief"]
    shown = brief if show_full else (brief[:240] + ("…" if len(brief) > 240 else ""))
    print(f"  {DIM}{shown}{RESET}")

    if voice_ok:
        print(f"  {_tick(True)} voice clean")
    else:
        by_cat: dict[str, list[str]] = {}
        for cat, frag in row["violations"]:
            by_cat.setdefault(cat, []).append(frag)
        leaks = "; ".join(f"{c}: {', '.join(sorted(set(f)))}" for c, f in by_cat.items())
        print(f"  {_tick(False)} voice leaks -> {leaks}")

    if "judge_error" in row:
        print(f"  {YELLOW}•{RESET} judge: {row['judge_error']}")
    elif judge:
        print(f"  {_tick(bool(judge_pass))} judge {judge.get('overall', '?')}/5 — "
              f"{judge.get('verdict', '')}")
        for key, val in (judge.get("criteria") or {}).items():
            ok = bool(val.get("pass"))
            note = val.get("note", "")
            print(f"      {_tick(ok)} {key}{('' if ok else f'  {DIM}{note}{RESET}')}")


def _print_summary(rows: list[dict], use_judge: bool) -> None:
    total = len(rows)
    errors = [r for r in rows if "error" in r]
    scored = [r for r in rows if "error" not in r]
    voice_clean = sum(1 for r in scored if r["voice_clean"])
    judged = [r for r in scored if "judge" in r]
    judge_pass = sum(1 for r in judged if r.get("judge_pass"))
    avg = (sum(int(r["judge"].get("overall", 0)) for r in judged) / len(judged)) if judged else 0

    print(f"\n{BOLD}{'─' * 60}{RESET}")
    print(f"{BOLD}Scorecard{RESET}  ({total} golden{'s' if total != 1 else ''})")
    print(f"  voice clean:   {voice_clean}/{len(scored)}")
    if use_judge and judged:
        print(f"  judge passed:  {judge_pass}/{len(judged)}   avg {avg:.1f}/5")
    if errors:
        print(f"  {RED}errors:        {len(errors)} ({', '.join(r['name'] for r in errors)}){RESET}")


def _save(rows: list[dict], use_judge: bool) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}.json"
    path.write_text(json.dumps({"run_at": stamp, "judged": use_judge, "results": rows}, indent=2))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the threshold eval harness.")
    ap.add_argument("--no-judge", action="store_true", help="voice guard only (fast, free)")
    ap.add_argument("--only", metavar="NAME", help="run a single golden by name")
    ap.add_argument("--full", action="store_true", help="print the full read text")
    ap.add_argument("--no-save", action="store_true", help="don't write the results JSON")
    args = ap.parse_args(argv)

    if args.only:
        g = GOLDENS_BY_NAME.get(args.only)
        if not g:
            print(f"No golden named {args.only!r}. Available: {', '.join(GOLDENS_BY_NAME)}")
            return 2
        goldens = [g]
    else:
        goldens = GOLDENS

    use_judge = not args.no_judge
    mode = "voice guard + judge" if use_judge else "voice guard only"
    print(f"Running {len(goldens)} golden{'s' if len(goldens) != 1 else ''} — {mode}")
    print(f"{DIM}(each read is a real claude call"
          f"{', plus one judge call' if use_judge else ''}; this takes a moment){RESET}")

    rows = []
    for g in goldens:
        rows.append(evaluate_one(g, use_judge))
        _print_row(rows[-1], args.full)

    _print_summary(rows, use_judge)
    if not args.no_save:
        path = _save(rows, use_judge)
        rel = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
        print(f"  {DIM}saved -> {rel}{RESET}")

    failed = any(
        ("error" in r) or (not r.get("voice_clean")) or ("judge" in r and not r.get("judge_pass"))
        for r in rows
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

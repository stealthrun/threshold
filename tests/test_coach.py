"""Tests for the orchestrator (Step 4).

These pin the wiring, not the pieces (each module is tested on its own): the right session
is selected, its detail is loaded before interpreting, the read reaches the vault, the block
is threaded through, and the pipeline degrades to a clear report — never a crash — when there
are no sessions or the model is unavailable. The network and the model are stubbed; nothing
here spawns a process or makes a request.
"""

import pytest

import coach

# Two runs in the window, newest first (the shape fetch_recent_with_plan returns).
SESSIONS = [
    {"source_id": "i200", "date": "2026-06-18", "activity_type": "threshold",
     "distance_km": 12.0, "avg_pace_sec_per_km": 250, "avg_hr": 162},
    {"source_id": "i199", "date": "2026-06-16", "activity_type": "easy",
     "distance_km": 8.0, "avg_pace_sec_per_km": 320, "avg_hr": 140},
]
RECENT = [{"label": "this week", "volume_km": 70, "sessions": 5, "read": "Solid week."}]
CREDS = ("athlete", "key")  # opaque here; the fetch is stubbed


@pytest.fixture
def wired(monkeypatch):
    """Stub every seam coach.py reaches out through, and record what it was handed so the
    wiring can be asserted. `calls` captures the cross-module hand-offs."""
    calls = {}

    monkeypatch.setattr(coach, "bootstrap_vault",
                        lambda v: calls.__setitem__("bootstrapped", v))
    monkeypatch.setattr(coach, "fetch_recent_with_plan",
                        lambda creds, weeks=4: (SESSIONS, RECENT))

    def fake_detail(creds, session):
        calls["detailed"] = session
        session["laps"] = [{"lap_type": "work"}]      # mark that detail was loaded
        return session
    monkeypatch.setattr(coach, "load_session_detail", fake_detail)

    def fake_interpret(session, recent, block):
        calls["interpreted"] = {"session": session, "recent": recent, "block": block}
        return "Your read."
    monkeypatch.setattr(coach, "interpret", fake_interpret)

    def fake_record(vault, session, read, block):
        calls["recorded"] = {"vault": vault, "session": session,
                             "read": read, "block": block}
        return "/vault/threshold/activities/note.md"
    monkeypatch.setattr(coach, "record_session", fake_record)

    return calls


# ── selection ──────────────────────────────────────────────────────────────────────────

def test_select_defaults_to_most_recent():
    assert coach.select_session(SESSIONS)["source_id"] == "i200"


def test_select_by_activity_id():
    assert coach.select_session(SESSIONS, activity_id="i199")["source_id"] == "i199"


def test_select_by_date():
    assert coach.select_session(SESSIONS, date="2026-06-16")["source_id"] == "i199"


def test_select_returns_none_when_nothing_matches():
    assert coach.select_session(SESSIONS, activity_id="nope") is None
    assert coach.select_session([]) is None


# ── block assembly ───────────────────────────────────────────────────────────────────────

def test_block_from_args_drops_unset_fields():
    assert coach._block_from_args("base", "build", 6, None, None) == {
        "name": "base", "phase": "build", "week": 6}


def test_block_from_args_all_none_is_none():
    assert coach._block_from_args(None, None, None, None, None) is None


# ── the pipeline wiring ──────────────────────────────────────────────────────────────────

def test_pipeline_reads_most_recent_and_records(wired):
    block = {"name": "base build", "phase": "build"}
    report = coach.coach_session(CREDS, "/vault", block=block)

    assert wired["bootstrapped"] == "/vault"                 # vault ensured first
    assert wired["detailed"]["source_id"] == "i200"          # focal = most recent
    # detail is loaded BEFORE interpret sees it (laps present on the interpreted session)
    assert wired["interpreted"]["session"]["laps"] == [{"lap_type": "work"}]
    assert wired["interpreted"]["recent"] == RECENT
    assert wired["interpreted"]["block"] == block            # full dict reaches interpret()
    assert wired["recorded"]["read"] == "Your read."
    assert wired["recorded"]["block"] == "base build"        # vault note links the block by name
    assert report["read"] == "Your read."
    assert report["note_path"] == "/vault/threshold/activities/note.md"


def test_pipeline_honours_activity_selection(wired):
    coach.coach_session(CREDS, "/vault", activity_id="i199")
    assert wired["detailed"]["source_id"] == "i199"


# ── graceful degradation ─────────────────────────────────────────────────────────────────

def test_no_matching_session_records_nothing(wired):
    report = coach.coach_session(CREDS, "/vault", activity_id="missing")
    assert report["session"] is None
    assert report["read"] is None and report["note_path"] is None
    assert "detailed" not in wired and "recorded" not in wired


def test_unavailable_model_does_not_record(wired, monkeypatch):
    monkeypatch.setattr(coach, "interpret", lambda *a, **k: None)
    report = coach.coach_session(CREDS, "/vault")
    assert report["session"]["source_id"] == "i200"          # session was still fetched
    assert report["read"] is None and report["note_path"] is None
    assert "recorded" not in wired                           # nothing written without a read


# ── bulk / sync (coach_all) ──────────────────────────────────────────────────────────────

@pytest.fixture
def bulk_wired(monkeypatch):
    """Stub the seams for coach_all and capture what gets recorded (a list, since bulk records
    more than one)."""
    recorded = []
    monkeypatch.setattr(coach, "bootstrap_vault", lambda v: None)
    monkeypatch.setattr(coach, "fetch_recent_with_plan", lambda c, weeks=4: (SESSIONS, RECENT))
    monkeypatch.setattr(coach, "load_session_detail", lambda c, s: s)
    monkeypatch.setattr(coach, "interpret", lambda s, r, b: f"read for {s['source_id']}")
    monkeypatch.setattr(coach, "record_session",
                        lambda v, s, read, block: recorded.append((s["source_id"], block)))
    return recorded


def test_all_records_new_and_skips_existing(bulk_wired, monkeypatch):
    monkeypatch.setattr(coach, "is_recorded", lambda v, s: s["source_id"] == "i199")  # i199 done
    res = coach.coach_all(CREDS, "/vault", block={"name": "base build"})
    assert res["recorded"] == ["i200"] and res["skipped"] == ["i199"]
    assert [sid for sid, _ in bulk_wired] == ["i200"]
    assert bulk_wired[0][1] == "base build"                   # block passed by name, not dict


def test_all_processes_oldest_first(bulk_wired, monkeypatch):
    monkeypatch.setattr(coach, "is_recorded", lambda v, s: False)
    res = coach.coach_all(CREDS, "/vault")
    assert res["recorded"] == ["i199", "i200"]               # oldest (i199) before newest (i200)


def test_all_force_rereads_recorded(bulk_wired, monkeypatch):
    monkeypatch.setattr(coach, "is_recorded", lambda v, s: True)   # everything already recorded
    res = coach.coach_all(CREDS, "/vault", force=True)
    assert set(res["recorded"]) == {"i199", "i200"} and res["skipped"] == []


def test_all_tracks_sessions_with_no_read(bulk_wired, monkeypatch):
    monkeypatch.setattr(coach, "is_recorded", lambda v, s: False)
    monkeypatch.setattr(coach, "interpret", lambda s, r, b: None)  # model unavailable
    res = coach.coach_all(CREDS, "/vault")
    assert set(res["no_read"]) == {"i199", "i200"} and res["recorded"] == []
    assert bulk_wired == []                                   # nothing recorded without a read

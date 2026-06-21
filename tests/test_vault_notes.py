"""Tests for the vault link graph (Step 3b).

Covers note rendering, the wikilink graph, same-type similarity, and the two memory
guarantees: idempotent rewrite by stable name, and the athlete's `## Notes` preserved
across rewrites. Runs against a real temp vault — no network.
"""

from pathlib import Path

import pytest

from vault import bootstrap
from vault import notes

VO2 = {
    "source_id": "i111", "date": "2026-06-15", "activity_type": "vo2",
    "distance_km": 9.5, "avg_pace_sec_per_km": 230, "avg_hr": 170, "max_hr": 178,
    "zone_dist": {"Z5": 0.4, "Z4": 0.3},
    "laps": [{"lap_type": "work", "distance_m": 800, "duration_sec": p * 800 // 1000,
              "avg_hr": h, "avg_pace_sec_per_km": p}
             for p, h in zip([184, 187, 192, 199, 205, 205],
                             [172, 175, 176, 177, 177, 178])],
    "plan_targets": {"work_rep_count": 6, "work_pace_target_sec_km": 185},
}
READ = "Your legs tapped out before your heart did. Drop a rep next time and hold the pace."


@pytest.fixture
def vault(tmp_path):
    bootstrap.bootstrap_vault(tmp_path)
    return tmp_path


# ── naming + helpers ──────────────────────────────────────────────────────────────────

def test_week_key():
    assert notes.week_key("2026-06-15") == "2026-W25"
    assert notes.week_key("bad") is None


def test_activity_basename_is_stable_on_source_id():
    assert notes.activity_basename(VO2) == "2026-06-15_vo2_i111"
    assert notes.activity_basename({"date": "2026-06-15", "activity_type": "easy"}) \
        == "2026-06-15_easy"


# ── rendering + graph ─────────────────────────────────────────────────────────────────

def test_record_session_writes_a_linked_note(vault):
    path = notes.record_session(vault, VO2, READ, block="competition")
    text = path.read_text(encoding="utf-8")

    assert path == vault / "threshold" / "activities" / "2026-06-15_vo2_i111.md"
    assert "type: vo2" in text                       # frontmatter
    assert "> Pace faded" in text                    # key_signal callout
    assert READ in text                              # the coach's read
    assert '"stimulus_quality"' in text              # machine-readable details
    assert "- Week: [[2026-W25]]" in text
    assert "- Block: [[competition]]" in text
    assert "- Type: [[vo2]]" in text


def test_record_session_creates_week_and_block_stubs(vault):
    notes.record_session(vault, VO2, READ, block="competition")
    assert (vault / "threshold" / "weeks" / "2026-W25.md").is_file()
    assert (vault / "threshold" / "blocks" / "competition.md").is_file()


def test_block_stub_links_from_week(vault):
    notes.record_session(vault, VO2, READ, block="competition")
    week = (vault / "threshold" / "weeks" / "2026-W25.md").read_text(encoding="utf-8")
    assert "[[competition]]" in week


# ── the memory guarantees ─────────────────────────────────────────────────────────────

def test_rewrite_is_idempotent_on_stable_name(vault):
    p1 = notes.record_session(vault, VO2, READ)
    p2 = notes.record_session(vault, VO2, "A revised read.")
    assert p1 == p2                                  # same note, updated in place
    assert "A revised read." in p2.read_text(encoding="utf-8")
    assert len(list((vault / "threshold" / "activities").glob("*.md"))) == 1


def test_rewrite_preserves_the_athletes_notes(vault):
    path = notes.record_session(vault, VO2, READ)
    # athlete adds their own observation under ## Notes
    text = path.read_text(encoding="utf-8").replace(
        "<!-- Your own observations. threshold never overwrites this section. -->",
        "Felt flat warming up but came good.",
    )
    path.write_text(text, encoding="utf-8")

    notes.record_session(vault, VO2, "Regenerated read.")          # rewrite
    after = path.read_text(encoding="utf-8")
    assert "Felt flat warming up but came good." in after          # preserved
    assert "Regenerated read." in after                            # read updated


def test_block_stub_not_overwritten(vault):
    notes.record_session(vault, VO2, READ, block="competition")
    block = vault / "threshold" / "blocks" / "competition.md"
    block.write_text("# competition\n\nMY CURATED BLOCK\n", encoding="utf-8")
    notes.record_session(vault, VO2, READ, block="competition")    # re-record
    assert block.read_text(encoding="utf-8") == "# competition\n\nMY CURATED BLOCK\n"


# ── similarity ────────────────────────────────────────────────────────────────────────

def test_find_similar_matches_same_type_only(vault):
    # two past vo2 sessions (one close, one far) + an easy run that must never match
    notes.record_session(vault, {**VO2, "source_id": "i100", "date": "2026-05-20",
                                  "distance_km": 9.6, "avg_pace_sec_per_km": 232,
                                  "avg_hr": 171}, "old vo2")
    notes.record_session(vault, {**VO2, "source_id": "i101", "date": "2026-05-06",
                                  "distance_km": 15.0, "avg_pace_sec_per_km": 300,
                                  "avg_hr": 150}, "far vo2")
    notes.record_session(vault, {"source_id": "i102", "date": "2026-05-10",
                                  "activity_type": "easy", "distance_km": 9.5,
                                  "avg_pace_sec_per_km": 230, "avg_hr": 170}, "easy")

    similar = notes.find_similar(vault / "threshold" / "activities", VO2)
    assert "2026-05-20_vo2_i100" in similar           # close vo2 matched
    assert all("easy" not in name for name in similar)  # easy never matched


def test_find_similar_links_into_the_note(vault):
    notes.record_session(vault, {**VO2, "source_id": "i100", "date": "2026-05-20"},
                         "old vo2")
    path = notes.record_session(vault, VO2, READ)     # has a prior same-type session
    assert "- Similar: [[2026-05-20_vo2_i100]]" in path.read_text(encoding="utf-8")

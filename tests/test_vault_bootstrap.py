"""Tests for the vault bootstrap (Step 3a).

The three properties the memory layer depends on: it scaffolds the skeleton + hubs, it is
idempotent and never overwrites, and it is non-invasive (only the threshold/ namespace is
touched). All run against a real temp directory — no network, no Obsidian.
"""

from pathlib import Path

import pytest

from derive_signals import RPE_BREATH_CEILING  # the taxonomy types the hubs must match
from vault import bootstrap


def test_bootstrap_creates_skeleton_and_hubs(tmp_path):
    report = bootstrap.bootstrap_vault(tmp_path)
    root = Path(report["root"])

    assert root == tmp_path / "threshold"
    for sub in bootstrap.SUBDIRS:
        assert (root / sub).is_dir()
    for name in bootstrap.TYPE_HUBS:
        assert (root / "types" / f"{name}.md").is_file()
    assert (root / "profile.md").is_file()
    assert (root / "index.md").is_file()
    assert report["existing"] == []          # first run creates everything


def test_type_hubs_match_the_taxonomy():
    # the hubs must cover exactly the types the engine classifies into
    assert set(bootstrap.TYPE_HUBS) == set(RPE_BREATH_CEILING)


def test_bootstrap_is_idempotent_and_never_overwrites(tmp_path):
    bootstrap.bootstrap_vault(tmp_path)

    # the athlete edits a hub — bootstrap must preserve it on a second run
    hub = tmp_path / "threshold" / "types" / "vo2.md"
    hub.write_text("# vo2\n\nMY OWN NOTES\n", encoding="utf-8")

    report = bootstrap.bootstrap_vault(tmp_path)
    assert report["created"] == []                       # nothing new
    assert "types/vo2.md" in report["existing"]
    assert hub.read_text(encoding="utf-8") == "# vo2\n\nMY OWN NOTES\n"  # untouched


def test_bootstrap_is_non_invasive(tmp_path):
    # an existing personal note in the vault root must be left alone
    personal = tmp_path / "my_journal.md"
    personal.write_text("private", encoding="utf-8")
    existing_dir = tmp_path / "Daily Notes"
    existing_dir.mkdir()

    bootstrap.bootstrap_vault(tmp_path)

    assert personal.read_text(encoding="utf-8") == "private"
    assert existing_dir.is_dir()
    # everything threshold created lives under the namespace, nothing else in root
    new_top_level = {p.name for p in tmp_path.iterdir()}
    assert new_top_level == {"my_journal.md", "Daily Notes", "threshold"}


def test_bootstrap_creates_vault_dir_for_new_user(tmp_path):
    # a brand-new athlete may point at a path that doesn't exist yet
    fresh = tmp_path / "BrandNewVault"
    report = bootstrap.bootstrap_vault(fresh)
    assert (fresh / "threshold" / "profile.md").is_file()
    assert len(report["created"]) == len(bootstrap.TYPE_HUBS) + 2  # hubs + profile + index


def test_bootstrap_rejects_a_file_path(tmp_path):
    f = tmp_path / "not_a_vault.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        bootstrap.bootstrap_vault(f)


def test_hub_note_carries_a_tag_for_the_graph():
    note = bootstrap._type_hub_note("vo2", "desc")
    assert "#vo2" in note          # the tag the Obsidian graph colours by
    assert note.startswith("# vo2")

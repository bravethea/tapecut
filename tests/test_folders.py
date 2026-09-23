# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""Connected folders: config round-trip, listing, and how failures read."""
import json
import os
import stat

import pytest

from core import folders, library


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """Point the whole library at a throwaway ~/Tapecut."""
    monkeypatch.setattr(library, "APP_DIR", tmp_path)
    monkeypatch.setattr(library, "TRANSCRIPTS_DIR", tmp_path / "transcripts")
    monkeypatch.setattr(library, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(library, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(library, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(library, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path


@pytest.fixture
def recordings(tmp_path):
    d = tmp_path / "recordings"
    (d / "nested").mkdir(parents=True)
    (d / "a.m4a").write_bytes(b"x" * 10)
    (d / "b.wav").write_bytes(b"x" * 20)
    (d / "nested" / "c.mp3").write_bytes(b"x" * 30)
    (d / "notes.txt").write_text("not a recording")
    (d / ".hidden.m4a").write_bytes(b"x")
    return d


# ---------------------------------------------------------------- connecting

def test_add_then_connected_round_trips(app_dir, recordings):
    folders.add(str(recordings), "Recorder")
    got = folders.connected()
    assert [f["name"] for f in got] == ["Recorder"]
    assert got[0]["readable"] is True


def test_add_persists_to_config_not_memory(app_dir, recordings):
    folders.add(str(recordings), "Recorder")
    written = json.loads((app_dir / "config.json").read_text())
    assert written["folders"][0]["name"] == "Recorder"


def test_name_defaults_to_the_folders_own_name(app_dir, recordings):
    entry = folders.add(str(recordings))
    assert entry["name"] == "recordings"


def test_adding_twice_is_refused(app_dir, recordings):
    folders.add(str(recordings))
    with pytest.raises(folders.FolderError, match="already connected"):
        folders.add(str(recordings))


def test_add_rejects_a_file(app_dir, recordings):
    with pytest.raises(folders.FolderError, match="Not a folder"):
        folders.add(str(recordings / "a.m4a"))


def test_add_rejects_a_missing_path(app_dir, tmp_path):
    with pytest.raises(folders.FolderError, match="No such folder"):
        folders.add(str(tmp_path / "nope"))


def test_remove_forgets_it(app_dir, recordings):
    folders.add(str(recordings))
    folders.remove(str(recordings))
    assert folders.connected() == []


def test_remove_is_silent_about_unknown_folders(app_dir, recordings):
    folders.remove(str(recordings))          # never connected — must not raise
    assert folders.connected() == []


def test_paths_under_home_are_stored_home_relative(app_dir, monkeypatch, tmp_path):
    """So a config file survives being moved to another account."""
    home = tmp_path / "home"
    (home / "Recordings").mkdir(parents=True)
    monkeypatch.setattr(folders.Path, "home", staticmethod(lambda: home))
    entry = folders.add(str(home / "Recordings"))
    assert entry["path"] == "~/Recordings"


# ---------------------------------------------------------------- listing

def test_list_media_finds_recordings_including_nested(app_dir, recordings):
    names = {f["name"] for f in folders.list_media(str(recordings))}
    assert names == {"a.m4a", "b.wav", "c.mp3"}


def test_list_media_skips_non_media_and_dotfiles(app_dir, recordings):
    names = {f["name"] for f in folders.list_media(str(recordings))}
    assert "notes.txt" not in names
    assert ".hidden.m4a" not in names


def test_list_media_is_newest_first(app_dir, recordings):
    os.utime(recordings / "a.m4a", (1_000, 1_000))
    os.utime(recordings / "b.wav", (9_000, 9_000))
    os.utime(recordings / "nested" / "c.mp3", (5_000, 5_000))
    assert [f["name"] for f in folders.list_media(str(recordings))] == [
        "b.wav", "c.mp3", "a.m4a",
    ]


def test_list_media_stops_at_max_depth(app_dir, recordings):
    deep = recordings / "one" / "two" / "three" / "four"
    deep.mkdir(parents=True)
    (deep / "deep.m4a").write_bytes(b"x")
    assert "deep.m4a" not in {f["name"] for f in folders.list_media(str(recordings))}


def test_list_media_carries_the_full_path_to_open(app_dir, recordings):
    entry = next(f for f in folders.list_media(str(recordings)) if f["name"] == "c.mp3")
    assert entry["path"] == str(recordings / "nested" / "c.mp3")


def test_list_media_on_a_missing_folder_says_so(app_dir, tmp_path):
    with pytest.raises(folders.FolderError, match="no longer exists"):
        folders.list_media(str(tmp_path / "gone"))


# ---------------------------------------------------------------- permissions

def test_unreadable_folder_names_full_disk_access(app_dir, tmp_path):
    """macOS blocks Voice Memos et al; the message must say what to do."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0)
    try:
        ok, why = folders.readable(str(blocked))
        if ok:
            pytest.skip("running as a user that ignores directory permissions")
        assert "Full Disk Access" in why
    finally:
        blocked.chmod(stat.S_IRWXU)


def test_connected_reports_a_folder_that_vanished(app_dir, tmp_path):
    gone = tmp_path / "gone"
    gone.mkdir()
    folders.add(str(gone))
    gone.rmdir()
    entry = folders.connected()[0]
    assert entry["readable"] is False
    assert "no longer exists" in entry["problem"]


# ---------------------------------------------------------------- suggestions

def test_suggestions_only_offer_paths_that_exist(app_dir, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "Music").mkdir(parents=True)
    monkeypatch.setattr(folders.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(folders, "SUGGESTED", [
        ("Music", "~/Music"),
        ("Nowhere", "~/Nowhere"),
    ])
    assert [s["name"] for s in folders.suggestions()] == ["Music"]


def test_suggestions_drop_what_is_already_connected(app_dir, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "Music").mkdir(parents=True)
    monkeypatch.setattr(folders.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(folders, "SUGGESTED", [("Music", "~/Music")])
    folders.add(str(home / "Music"), "Music")
    assert folders.suggestions() == []


def test_suggested_paths_carry_nothing_personal():
    """The shipped list is standard macOS locations, never someone's own."""
    for _name, path in folders.SUGGESTED:
        assert path.startswith("~/"), path
        assert "/Users/" not in path

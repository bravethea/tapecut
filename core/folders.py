# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Connected folders — local directories you browse from the rail, the way you
browse Drive.

The point is apps that keep their recordings somewhere fixed and awkward: Voice
Memos, a podcast recorder, a field recorder's SD-card mount. Connect the folder
once and its recordings are a click away instead of a trip through Finder.

Connections live in ~/Tapecut/config.json under "folders" — so they are yours,
per-machine, and never in the repository:

    "folders": [{"name": "Voice Memos", "path": "~/Library/…/Recordings"}]

Nothing is copied or moved. Tapecut reads the files where they are, and the
transcript goes to the library as usual, so the app that owns the folder never
sees a change.

macOS privacy note: several interesting folders (Voice Memos, Desktop,
Documents, Downloads) are TCC-protected. Reading one raises PermissionError
until the user grants Full Disk Access to whatever runs the server, so every
listing reports `readable` and the UI can say so instead of showing an empty
folder and looking broken.
"""
import os
import sys
from pathlib import Path

from core import library
from core.transcriber import SUPPORTED_FORMATS

# Standard macOS locations worth offering as one-click connections. These are
# the same for every user — there is nothing personal in this list, and a
# suggestion is only shown when the path actually exists on the machine.
SUGGESTED = [
    ("Voice Memos", "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"),
    ("Music", "~/Music"),
    ("Movies", "~/Movies"),
    ("Downloads", "~/Downloads"),
    ("Desktop", "~/Desktop"),
]

MAX_DEPTH = 3       # Voice Memos nests recordings; a flat scan would miss them
MAX_FILES = 500     # a listing is a rail, not an archive browser


class FolderError(RuntimeError):
    pass


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(str(path)))


def _tidy(path: str) -> str:
    """Store paths home-relative, so a config survives a different username."""
    p = _expand(path)
    try:
        return "~/" + p.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(p)


def readable(path: str) -> tuple[bool, str]:
    """(is_readable, why_not). Distinguishes 'missing' from 'macOS says no'."""
    p = _expand(path)
    if not p.exists():
        return False, "This folder no longer exists."
    if not p.is_dir():
        return False, "That is a file, not a folder."
    try:
        next(p.iterdir(), None)
    except PermissionError:
        if sys.platform != "darwin":
            return False, "You don't have permission to read this folder."
        return False, (
            "macOS is blocking this folder. Give Full Disk Access to whatever "
            "runs Tapecut (System Settings → Privacy & Security → Full Disk "
            "Access), then restart the server."
        )
    except OSError as e:
        return False, f"Could not read this folder: {e.strerror or e}"
    return True, ""


def connected() -> list[dict]:
    """Folders the user has connected, each with its current reachability."""
    out = []
    for entry in library.load_config().get("folders") or []:
        path = entry.get("path") or ""
        if not path:
            continue
        ok, why = readable(path)
        out.append({
            "name": entry.get("name") or _expand(path).name or path,
            "path": _tidy(path),
            "readable": ok,
            "problem": why,
        })
    return out


def suggestions() -> list[dict]:
    """Standard locations not yet connected, that exist on this machine."""
    already = {f["path"] for f in connected()}
    out = []
    for name, path in SUGGESTED:
        if _tidy(path) in already:
            continue
        if _expand(path).is_dir():
            out.append({"name": name, "path": _tidy(path)})
    return out


def add(path: str, name: str = "") -> dict:
    """Connect a folder. Raises FolderError if it is not usable."""
    p = _expand(path)
    if not p.exists():
        raise FolderError(f"No such folder: {p}")
    if not p.is_dir():
        raise FolderError(f"Not a folder: {p}")

    stored = _tidy(path)
    cfg = library.load_config()
    folders = list(cfg.get("folders") or [])
    if any(f.get("path") == stored for f in folders):
        raise FolderError("That folder is already connected.")

    entry = {"name": (name or p.name or stored).strip(), "path": stored}
    folders.append(entry)
    cfg["folders"] = folders
    library.save_config(cfg)

    ok, why = readable(stored)
    return {**entry, "readable": ok, "problem": why}


def remove(path: str) -> None:
    stored = _tidy(path)
    cfg = library.load_config()
    folders = [f for f in (cfg.get("folders") or []) if f.get("path") != stored]
    cfg["folders"] = folders
    library.save_config(cfg)


def list_media(path: str) -> list[dict]:
    """
    Every supported recording in the folder, newest first, with the same badges
    the Drive listing carries so the rail rows look and behave identically.

    Searched a few levels deep because apps nest: Voice Memos keeps each
    recording in its own subfolder.
    """
    p = _expand(path)
    ok, why = readable(str(p))
    if not ok:
        raise FolderError(why)

    root_depth = len(p.parts)
    files: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(p, onerror=lambda e: None):
        here = Path(dirpath)
        if len(here.parts) - root_depth >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith(".") or Path(fn).suffix.lower() not in SUPPORTED_FORMATS:
                continue
            f = here / fn
            try:
                st = f.stat()
            except OSError:
                continue
            files.append({
                "name": fn,
                "path": str(f),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "transcribed": library.has(fn, st.st_size),
            })
            if len(files) >= MAX_FILES:
                break
        if len(files) >= MAX_FILES:
            break

    files.sort(key=lambda f: f["mtime"], reverse=True)   # newest first: you
    return files                                          # usually want the last one

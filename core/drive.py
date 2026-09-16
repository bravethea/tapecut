# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Google Drive access via rclone (read-only remote "gdrive:").

Files are downloaded on demand into ~/Tapecut/cache and the cache is pruned
to the most recent few files, so recordings never accumulate locally.
Transcripts persist in the library (core/library.py) independent of the cache.
"""
import json
import random
import shutil
import subprocess
from pathlib import Path

from core import library
from core.transcriber import SUPPORTED_FORMATS

CACHE_KEEP = 3          # newest cached media files to keep
LIST_TIMEOUT = 60       # s
FETCH_TIMEOUT = 3600    # s — big video over slow uplink


class DriveError(RuntimeError):
    pass


def _rclone(*args: str, timeout: int = LIST_TIMEOUT) -> str:
    if not shutil.which("rclone"):
        raise DriveError("rclone is not installed — run: brew install rclone")
    try:
        result = subprocess.run(
            ["rclone", *args], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise DriveError(f"rclone timed out after {timeout}s")
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        raise DriveError(detail[-1] if detail else "rclone failed")
    return result.stdout


def is_configured() -> bool:
    try:
        remote = library.load_config()["drive_remote"]
        return remote in _rclone("listremotes", timeout=10).split()
    except DriveError:
        return False


def remote_path(folder: str, name: str = "") -> str:
    remote = library.load_config()["drive_remote"]
    base = remote + folder.strip("/")
    return f"{base}/{name}" if name else base


def list_folder(folder: str) -> tuple[list[str], list[dict]]:
    """Returns (subdir_names, media_files). Raises DriveError on failure."""
    items = json.loads(_rclone("lsjson", remote_path(folder)))
    dirs, files = [], []
    for it in items:
        if it["IsDir"]:
            dirs.append(it["Name"])
        elif Path(it["Name"]).suffix.lower() in SUPPORTED_FORMATS:
            cached = library.CACHE_DIR / it["Name"]
            files.append({
                "name": it["Name"],
                "size": it["Size"],
                "mtime": (it.get("ModTime") or "")[:10],
                "transcribed": library.has(it["Name"], it["Size"]),
                "cached": cached.exists() and cached.stat().st_size == it["Size"],
            })
    dirs.sort(key=str.lower)
    files.sort(key=lambda f: f["name"].lower())
    return dirs, files


def pick_random(files: list[dict]) -> dict:
    """Random recording — prefers ones without a transcript yet."""
    if not files:
        raise DriveError("No recordings in this folder")
    fresh = [f for f in files if not f["transcribed"]]
    return random.choice(fresh or files)


def fetch(folder: str, name: str, size: int) -> str:
    """
    Ensure the file is in the local cache; download if needed. Returns the
    local path. Evicts older cached files beyond CACHE_KEEP afterwards.
    """
    library.ensure_dirs()
    target = library.CACHE_DIR / name
    if target.exists() and target.stat().st_size == size:
        target.touch()  # refresh LRU position
        return str(target)
    _rclone("copyto", remote_path(folder, name), str(target), timeout=FETCH_TIMEOUT)
    evict_cache(keep_path=target)
    return str(target)


def evict_cache(keep_path: Path | None = None) -> None:
    files = [p for p in library.CACHE_DIR.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[CACHE_KEEP:]:
        if keep_path and p == keep_path:
            continue
        try:
            p.unlink()
        except OSError:
            pass


def parse_remote(source: str) -> tuple[str, str] | None:
    """
    Split a stored source like "gdrive:folder/sub/file.m4a" into (folder, name).
    Returns None if the source is not a Drive path.
    """
    remote = library.load_config()["drive_remote"]
    if not source.startswith(remote):
        return None
    rest = source[len(remote):].strip("/")
    if "/" not in rest:
        return "", rest
    folder, name = rest.rsplit("/", 1)
    return folder, name


def fetch_remote(source: str) -> str:
    """
    Ensure a Drive-sourced recording is in the cache, downloading if needed.
    Takes the stored source string; returns the local path.
    """
    parsed = parse_remote(source)
    if parsed is None:
        raise DriveError(f"Not a Drive path: {source}")
    folder, name = parsed
    library.ensure_dirs()
    target = library.CACHE_DIR / name
    if target.exists() and target.stat().st_size > 0:
        target.touch()
        return str(target)
    _rclone("copyto", source, str(target), timeout=FETCH_TIMEOUT)
    evict_cache(keep_path=target)
    return str(target)


def copy_to(source: str, target) -> str:
    """Copy any Drive path (e.g. an image in 'media assets') to a local file."""
    _rclone("copyto", source, str(target), timeout=FETCH_TIMEOUT)
    return str(target)


def find_by_name(name: str, root: str | None = None) -> str | None:
    """
    Search Drive for a recording by exact filename, returning its full remote
    path (or None). Used to relocate a recording whose stored source no longer
    resolves — e.g. an entry saved before its Drive origin was tracked.
    Searches recursively from the parent of the configured folder.
    """
    if root is None:
        folder = library.load_config()["drive_folder"].strip("/")
        root = folder.rsplit("/", 1)[0] if "/" in folder else folder
    try:
        out = _rclone("lsf", "--recursive", "--files-only",
                      remote_path(root), timeout=180)
    except DriveError:
        return None
    for line in out.splitlines():
        if Path(line).name == name:
            return remote_path(root, line)
    return None

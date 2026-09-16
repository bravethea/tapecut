# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Project persistence — save/load the transcript and edit state as a sidecar
JSON next to the media file, so transcription is only ever done once and
edits survive app restarts.
"""
import json
import time
from pathlib import Path

SIDECAR_SUFFIX = ".tapecut.json"


def sidecar_path(media_path: str) -> Path:
    return Path(media_path).with_suffix(Path(media_path).suffix + SIDECAR_SUFFIX)


def has_project(media_path: str) -> bool:
    return sidecar_path(media_path).exists()


def save_project(media_path: str, words: list[dict], prompt: str = "") -> Path:
    path = sidecar_path(media_path)
    data = {
        "version": 1,
        "media_path": str(media_path),
        "prompt": prompt,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "words": words,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return path


def load_project(media_path: str) -> dict:
    """Returns {"words": [...], "prompt": str}. Raises on missing/corrupt file."""
    data = json.loads(sidecar_path(media_path).read_text())
    words = data["words"]
    for w in words:  # ensure required keys exist
        w.setdefault("deleted", False)
    return {"words": words, "prompt": data.get("prompt", "")}

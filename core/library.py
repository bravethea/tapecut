# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Central transcript library + app dirs.

All transcripts (and edit state) are stored in ~/Tapecut/transcripts — one JSON
per recording plus a plain-text .txt for reading/searching outside the app.
This replaces the per-file sidecar (which is still read as a legacy fallback),
and is what makes Drive recordings work: the cached media file can be evicted,
the transcript stays.

~/Tapecut/
  config.json      app settings (drive remote + folder)
  transcripts/     <stem>__<hash>.json + .txt   ← permanent
  cache/           temporarily downloaded Drive files ← auto-evicted
  exports/         edited output for Drive-sourced recordings
  assets/          cover images used when rendering audio to YouTube MP4
"""
import hashlib
import json
import time
from pathlib import Path

APP_DIR = Path.home() / "Tapecut"
TRANSCRIPTS_DIR = APP_DIR / "transcripts"
CACHE_DIR = APP_DIR / "cache"
EXPORTS_DIR = APP_DIR / "exports"
ASSETS_DIR = APP_DIR / "assets"      # cover images for audio→video export
CONFIG_PATH = APP_DIR / "config.json"

# Shipped defaults only. Whatever you set in ~/Tapecut/config.json wins, and
# that file is yours — it never lives in the repository.
DEFAULT_CONFIG = {
    "drive_remote": "gdrive:",   # any read-only rclone remote; see docs/MANUAL.md
    "drive_folder": "",          # "" = the remote's root; browse down from there
}


def ensure_dirs() -> None:
    for d in (APP_DIR, TRANSCRIPTS_DIR, CACHE_DIR, EXPORTS_DIR, ASSETS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    ensure_dirs()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1))


# ------------------------------------------------------------------ keys

def media_key(media_path: str) -> str:
    """
    Stable identity for a recording: filename + size. Survives the file moving
    between Drive cache, local disk, etc. (same content → same key).
    """
    p = Path(media_path)
    size = p.stat().st_size if p.exists() else 0
    digest = hashlib.sha1(f"{p.name}:{size}".encode()).hexdigest()[:8]
    return f"{p.stem}__{digest}"


def _json_path(key: str) -> Path:
    return TRANSCRIPTS_DIR / f"{key}.json"


# ------------------------------------------------------------------ save/load

def save(media_path: str, words: list[dict], prompt: str = "", source: str = "",
         pause_cuts: list[int] | None = None,
         speaker_names: dict | None = None, analyses: dict | None = None) -> str:
    """Save transcript + edits. Returns the library key."""
    ensure_dirs()
    key = media_key(media_path)
    entry = {
        "version": 1,
        "key": key,
        "media_name": Path(media_path).name,
        "source": source or str(media_path),
        "prompt": prompt,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_sec": round(words[-1]["end"], 2) if words else 0,
        "pause_cuts": sorted(pause_cuts or []),
        # SPEAKER_00 -> "Teodora", set by the user after diarization
        "speaker_names": speaker_names or {},
        # saved summaries/meeting notes/todos, keyed by analysis kind
        "analyses": analyses or {},
        "words": words,
    }
    _json_path(key).write_text(json.dumps(entry, ensure_ascii=False, indent=1))

    # readable sidecar: speaker labels where known, cut words in [brackets]
    from core.textexport import to_text
    body = to_text(words, names=entry["speaker_names"], include_cut=True)
    (TRANSCRIPTS_DIR / f"{key}.txt").write_text(
        f"# {entry['media_name']} — saved {entry['saved_at']}\n"
        f"# cut words shown in [brackets]\n\n" + body
    )
    return key


def load(media_path: str) -> dict | None:
    """Load transcript for a media file, or None. Words get `deleted` defaults."""
    path = _json_path(media_key(media_path))
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text())
    except Exception:
        return None
    for w in entry.get("words", []):
        w.setdefault("deleted", False)
    entry.setdefault("pause_cuts", [])
    entry.setdefault("speaker_names", {})
    entry.setdefault("analyses", {})
    return entry


def has(media_name: str, size: int) -> bool:
    """Check by name+size without needing the file locally (for Drive listings)."""
    digest = hashlib.sha1(f"{media_name}:{size}".encode()).hexdigest()[:8]
    return _json_path(f"{Path(media_name).stem}__{digest}").exists()


def get(key: str) -> dict | None:
    path = _json_path(key)
    if not path.exists() or path.parent != TRANSCRIPTS_DIR:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_all() -> list[dict]:
    """Summaries of every stored transcript, newest first."""
    ensure_dirs()
    entries = []
    for path in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            e = json.loads(path.read_text())
            words = e.get("words", [])
            entries.append({
                "key": e.get("key", path.stem),
                "media_name": e.get("media_name", path.stem),
                "source": e.get("source", ""),
                "saved_at": e.get("saved_at", ""),
                "duration_sec": e.get("duration_sec", 0),
                "n_words": len(words),
                "n_cut": sum(1 for w in words if w.get("deleted")),
                "speakers": [e.get("speaker_names", {}).get(s, s)
                             for s in dict.fromkeys(
                                 w["speaker"] for w in words if w.get("speaker"))],
                "analyses": sorted(e.get("analyses", {})),
            })
        except Exception:
            continue
    entries.sort(key=lambda e: e["saved_at"], reverse=True)
    return entries

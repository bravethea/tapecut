# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Playback conversion.

Some formats ffmpeg reads happily cannot be played by a browser: .wma, .aiff,
.avi, and (depending on their codecs) .mov and .mkv. Since the editor's preview
is an HTML <video> element, those files need a browser-friendly copy before you
can hear or see them.

The conversion is for PLAYBACK ONLY — transcription and export always read the
original file, so timestamps and quality are untouched. Converted copies live in
~/Tapecut/cache/playback and are pruned like the media cache.

When the source already carries browser-safe codecs (H.264 video / AAC audio in
a .mov, say) the file is remuxed with `-c copy`, which takes a second or two
instead of a full re-encode.
"""
import hashlib
import shutil
import subprocess
from pathlib import Path

from core import library

# Containers/codecs Chrome and Safari play directly from a plain HTTP range
# server. Anything else gets converted.
BROWSER_SAFE_EXTS = {".mp3", ".wav", ".m4a", ".mp4", ".flac", ".opus", ".ogg", ".oga", ".webm"}
SAFE_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
SAFE_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "pcm_s16le"}

PLAYBACK_DIR_NAME = "playback"
PLAYBACK_KEEP = 4          # converted copies to retain
CONVERT_TIMEOUT = 3600


class ConversionError(RuntimeError):
    pass


def playback_dir() -> Path:
    d = library.CACHE_DIR / PLAYBACK_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def needs_conversion(path: str) -> bool:
    return Path(path).suffix.lower() not in BROWSER_SAFE_EXTS


def _streams(path: str) -> list[tuple[str, str]]:
    """[(codec_type, codec_name), ...] via ffprobe."""
    if not shutil.which("ffprobe"):
        return []
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return []
    out = []
    for line in result.stdout.strip().splitlines():
        parts = [p for p in line.split(",") if p]
        if len(parts) == 2:
            name, kind = parts          # ffprobe prints codec_name,codec_type
            out.append((kind, name))
    return out


def _target_for(path: str) -> Path:
    """
    Cache name for the converted copy. The digest covers the absolute path,
    size and mtime, so two different sources that merely share a stem
    (session.wma vs session.aiff) can never collide onto one another's copy.
    """
    src = Path(path).resolve()
    try:
        st = src.stat()
        fingerprint = f"{src}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        fingerprint = str(src)
    digest = hashlib.sha1(fingerprint.encode()).hexdigest()[:10]
    has_video = any(k == "video" for k, _ in _streams(path))
    suffix = ".mp4" if has_video else ".m4a"
    return playback_dir() / f"{src.stem}__{digest}{suffix}"


def to_playable(path: str) -> str:
    """
    Return a path the browser can play. Converts if needed (cached), otherwise
    returns the original path unchanged.
    """
    if not needs_conversion(path):
        return path
    if not shutil.which("ffmpeg"):
        raise ConversionError("ffmpeg not found. Install with: brew install ffmpeg")

    target = _target_for(path)
    if target.is_file() and target.stat().st_size > 0:
        target.touch()
        return str(target)

    streams = _streams(path)
    video_codecs = [c for k, c in streams if k == "video"]
    audio_codecs = [c for k, c in streams if k == "audio"]
    # remux instead of re-encoding when the existing codecs are already safe
    can_copy = (
        all(c in SAFE_VIDEO_CODECS for c in video_codecs)
        and all(c in SAFE_AUDIO_CODECS for c in audio_codecs)
        and bool(audio_codecs or video_codecs)
    )

    cmd = ["ffmpeg", "-i", str(path)]
    if can_copy:
        cmd += ["-c", "copy"]
    elif video_codecs:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-vn", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-movflags", "+faststart", "-y", str(target)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=CONVERT_TIMEOUT)
    if result.returncode != 0 and can_copy:
        # some containers refuse a straight copy — fall back to a real encode
        cmd = ["ffmpeg", "-i", str(path)]
        cmd += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p"] if video_codecs else ["-vn"])
        cmd += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(target)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CONVERT_TIMEOUT)

    if result.returncode != 0:
        target.unlink(missing_ok=True)
        raise ConversionError(
            "Could not convert this file for playback:\n"
            + (result.stderr or "").strip()[-800:]
        )

    _prune()
    return str(target)


def _prune() -> None:
    files = [p for p in playback_dir().iterdir() if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[PLAYBACK_KEEP:]:
        try:
            p.unlink()
        except OSError:
            pass

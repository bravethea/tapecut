# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import subprocess
import shutil
from pathlib import Path
from pydub import AudioSegment

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}


def is_video_file(path: str) -> bool:
    """Extension-level guess. Prefer has_video_stream() for real decisions."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


_video_stream_cache: dict[tuple[str, int, float], bool] = {}


def has_video_stream(path: str) -> bool:
    """
    True only if the file really carries a picture track.

    The extension lies often enough to matter: an .mp4 export from a voice
    recorder holds AAC audio and no video stream at all. Treating those as
    video shows an empty player and breaks video export (which maps [0:v]).
    Result is cached per (path, size, mtime).
    """
    f = Path(path)
    try:
        key = (str(f), f.stat().st_size, f.stat().st_mtime)
    except OSError:
        return False
    if key in _video_stream_cache:
        return _video_stream_cache[key]

    verdict = False
    if shutil.which("ffprobe"):
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(f)],
                capture_output=True, text=True, timeout=30,
            )
            verdict = "video" in result.stdout
        except Exception:
            verdict = False
    _video_stream_cache[key] = verdict
    return verdict


def export_audio(segment: AudioSegment, output_path: str) -> None:
    """
    Export a pydub AudioSegment to mp3 or wav.
    Format is inferred from the output_path extension.
    Raises RuntimeError if ffmpeg is missing or export fails.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found. Install with: brew install ffmpeg"
        )

    ext = Path(output_path).suffix.lower().lstrip(".")
    if ext not in {"mp3", "wav"}:
        raise ValueError(f"Unsupported export format: {ext}")

    segment.export(output_path, format=ext)


def export_via_ffmpeg(input_path: str, segments: list[tuple[float, float]], output_path: str) -> None:
    """
    Direct ffmpeg export using a concat filter — avoids loading entire audio into memory.
    Useful for very long files. segments is a list of (start_sec, end_sec) tuples.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")

    if not segments:
        raise ValueError("No segments to export")

    # Build ffmpeg concat filter
    filter_parts = []
    inputs = []
    for i, (start, end) in enumerate(segments):
        inputs += ["-ss", str(start), "-to", str(end), "-i", input_path]
        filter_parts.append(f"[{i}:a]")

    n = len(segments)
    filter_str = "".join(filter_parts) + f"concat=n={n}:v=0:a=1[out]"

    cmd = inputs + [
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-y", output_path,
    ]

    result = subprocess.run(["ffmpeg"] + cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")


def export_video_via_ffmpeg(
    input_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> None:
    """
    Export edited VIDEO: keep only the given (start_sec, end_sec) ranges.
    Uses ffmpeg trim/atrim + concat filters in a single pass. Re-encodes video
    (H.264, CRF 18) + audio (AAC) — frame-accurate cuts, YouTube-ready output.
    (Note: select/aselect was tried first but ffmpeg 8.0's aselect does not
    drop audio frames reliably; trim+concat is exact.)
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")
    if not segments:
        raise ValueError("No segments to export")

    parts = []
    concat_inputs = []
    for i, (s, e) in enumerate(segments):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs.append(f"[v{i}][a{i}]")
    filter_complex = (
        ";".join(parts) + ";"
        + "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a=1[v][a]"
    )

    cmd = [
        "ffmpeg", "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-y", output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")


def export_audio_as_video(
    audio_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
    cover_path: str,
) -> None:
    """
    Export an AUDIO-only recording as a YouTube-ready MP4: the edited audio
    over a static cover image.

    One ffmpeg pass — the cover is looped as a still video track and the kept
    ranges are cut from the audio with atrim/concat (same exact semantics as
    export_video_via_ffmpeg). The image is scaled/padded to 1920x1080 so any
    aspect ratio works. `-tune stillimage` keeps the video track tiny: an
    identical frame stream costs almost no bitrate.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install with: brew install ffmpeg")
    if not segments:
        raise ValueError("No segments to export")
    if not Path(cover_path).is_file():
        raise RuntimeError(f"Cover image not found: {cover_path}")

    parts, concat_inputs = [], []
    for i, (s, e) in enumerate(segments):
        parts.append(f"[1:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs.append(f"[a{i}]")
    audio_chain = (
        ";".join(parts) + ";"
        + "".join(concat_inputs) + f"concat=n={len(segments)}:v=0:a=1[aout]"
    )
    video_chain = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,format=yuv420p[vout]"
    )
    filter_complex = f"{video_chain};{audio_chain}"

    cmd = [
        "ffmpeg",
        "-loop", "1", "-framerate", "24", "-i", str(cover_path),
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-crf", "26", "-pix_fmt", "yuv420p", "-r", "24", "-g", "48",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        "-y", output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")

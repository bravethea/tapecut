# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Tapecut web server — browser UI on localhost, reusing the core engine.

The browser plays the ORIGINAL media file directly (<video>/<audio> with HTTP
range requests) and skips cut regions in JavaScript, so preview is instant —
no server-side audio rebuild needed. Transcription, Drive downloads and export
run here as background jobs polled by the client.

Google Drive: read-only via rclone remote "gdrive:" (core/drive.py). Files are
cached temporarily in ~/Tapecut/cache; transcripts persist in
~/Tapecut/transcripts (core/library.py).

Run:  venv/bin/python -m web.server   (then open http://127.0.0.1:8756)
"""
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow running as a script

from flask import Flask, jsonify, request, send_file, send_from_directory

from core.transcriber import transcribe, is_model_cached, SUPPORTED_FORMATS
from core.audio_editor import (
    compute_kept_segments, build_edited_audio, pause_cut_ranges, subtract_ranges,
)
from core.export import (
    export_video_via_ffmpeg, is_video_file, has_video_stream,
    export_audio, export_audio_as_video,
)
from core import (
    project, library, drive, convert, disfluency, diarize, textexport, summarize,
)

STATIC_DIR = Path(__file__).parent / "static"
HOST = "127.0.0.1"
# 8756 by default (the URL the README and bookmarks use); PORT env overrides it
PORT = int(os.environ.get("PORT") or 8756)

app = Flask(__name__)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _start_job(target, *args) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "started": time.time()}

    def run():
        try:
            result = target(*args)
            with _jobs_lock:
                _jobs[job_id].update(status="done", result=result)
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id].update(status="error", error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return job_id


def _valid_media_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format: {path.suffix or '(no extension)'}. Supported: "
            + ", ".join(sorted(e.lstrip(".") for e in SUPPORTED_FORMATS))
        )
    return path


def _audio_peak_db(path: Path, sample_sec: int = 60) -> float | None:
    """Peak volume (dBFS) of the first sample_sec — cheap dead-recording check."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-t", str(sample_sec), "-i", str(path),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        for line in result.stderr.splitlines():
            if "max_volume" in line:
                return float(line.rsplit("max_volume:", 1)[1].replace("dB", "").strip())
    except Exception:
        pass
    return None


def _open_payload(path: Path, source: str = "") -> dict:
    """Everything the client needs to load a recording into the editor."""
    words, prompt, pause_cuts = None, "", []
    speaker_names, analyses = {}, {}
    entry = library.load(str(path))
    if entry:
        words, prompt = entry["words"], entry.get("prompt", "")
        pause_cuts = entry.get("pause_cuts", [])
        speaker_names = entry.get("speaker_names", {})
        analyses = entry.get("analyses", {})
        # keep a known Drive origin: opening the cached copy locally must not
        # overwrite it, or the recording can't be re-fetched once evicted
        if not source and drive.parse_remote(entry.get("source", "")):
            source = entry["source"]
    elif project.has_project(str(path)):      # legacy per-file sidecar
        try:
            saved = project.load_project(str(path))
            words, prompt = saved["words"], saved["prompt"]
        except Exception:
            pass

    peak_db = _audio_peak_db(path)
    return {
        "path": str(path),
        "name": path.name,
        "source": source or str(path),
        "is_video": has_video_stream(str(path)),
        # an .mp4/.mov that turns out to hold only audio (common with voice
        # recorders) — the UI explains why there is no picture
        "audio_in_video_container": is_video_file(str(path)) and not has_video_stream(str(path)),
        "words": words,
        "prompt": prompt,
        "pause_cuts": pause_cuts,
        "silent": peak_db is not None and peak_db < -60,
        # formats a browser cannot play (.wma/.aiff/.avi/.mov/.mkv) need a
        # converted copy before the preview player can use them
        "needs_conversion": convert.needs_conversion(str(path)),
        "model_cached": is_model_cached(),
        "speaker_names": speaker_names,
        "analyses": analyses,
        "diarization_available": diarize.is_available(),
    }


# ---------------------------------------------------------------- pages/media

@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(STATIC_DIR, name)


@app.get("/media")
def media():
    """Serve the original media file with Range support (needed for seeking)."""
    try:
        path = _valid_media_path(request.args.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return send_file(path, conditional=True)


# ---------------------------------------------------------------- local files

@app.post("/api/open")
def api_open():
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(_open_payload(path))


BROWSE_SCRIPT = """
try
    tell application "System Events"
        activate
        set theFile to choose file with prompt "Choose a recording" ¬
            of type {"public.audio", "public.movie"} ¬
            default location (path to home folder)
    end tell
    return POSIX path of theFile
on error number -128
    return "__CANCELLED__"
end try
"""


@app.post("/api/browse")
def api_browse():
    """
    Open the real macOS file picker and return the chosen path.

    The browser cannot hand a filesystem path to the server (an <input
    type=file> only yields a copy of the bytes), but this server runs on the
    user's own Mac — so we ask macOS for a native Open dialog and get the true
    path back. Runs as a job because the dialog blocks until the user answers.
    """
    def work():
        result = subprocess.run(
            ["osascript", "-e", BROWSE_SCRIPT],
            capture_output=True, text=True, timeout=600,
        )
        chosen = result.stdout.strip()
        if result.returncode != 0:
            detail = (result.stderr or "").strip()
            if not detail:            # dialog dismissed or process ended
                return {"cancelled": True}
            raise RuntimeError(detail.splitlines()[-1])
        if not chosen or chosen == "__CANCELLED__":
            return {"cancelled": True}
        path = _valid_media_path(chosen)          # raises on unsupported type
        return _open_payload(path)

    return jsonify({"job": _start_job(work)})


@app.post("/api/convert")
def api_convert():
    """Make a browser-playable copy of a file (job). Cached; original untouched."""
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    def work():
        return {"play_path": convert.to_playable(str(path))}

    return jsonify({"job": _start_job(work)})


# ---------------------------------------------------------------- google drive

@app.get("/api/drive/status")
def api_drive_status():
    cfg = library.load_config()
    return jsonify({
        "configured": drive.is_configured(),
        "folder": cfg["drive_folder"],
        "cache_keep": drive.CACHE_KEEP,
    })


@app.post("/api/drive/folder")
def api_drive_folder():
    data = request.get_json(force=True)
    cfg = library.load_config()
    cfg["drive_folder"] = data.get("folder", "").strip().strip("/")
    library.save_config(cfg)
    return jsonify({"ok": True, "folder": cfg["drive_folder"]})


@app.get("/api/drive/list")
def api_drive_list():
    folder = request.args.get("folder") or library.load_config()["drive_folder"]
    try:
        dirs, files = drive.list_folder(folder)
    except drive.DriveError as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({"folder": folder, "dirs": dirs, "files": files})


@app.post("/api/drive/fetch")
def api_drive_fetch():
    """Download a recording (or a random one) to the cache; returns a job."""
    data = request.get_json(force=True)
    folder = data.get("folder") or library.load_config()["drive_folder"]

    try:
        if data.get("random"):
            _dirs, files = drive.list_folder(folder)
            chosen = drive.pick_random(files)
            name, size = chosen["name"], chosen["size"]
        else:
            name, size = data["name"], data["size"]
    except drive.DriveError as e:
        return jsonify({"error": str(e)}), 502

    def work():
        local = drive.fetch(folder, name, size)
        payload = _open_payload(Path(local), source=drive.remote_path(folder, name))
        return payload

    return jsonify({"job": _start_job(work), "name": name})


# ---------------------------------------------------------------- library

@app.post("/api/disfluencies")
def api_disfluencies():
    """Repetitions and stutters in a word list, for crossing out in the UI."""
    data = request.get_json(force=True)
    return jsonify(disfluency.find_all(data.get("words", [])))


@app.get("/api/library")
def api_library():
    return jsonify({"entries": library.list_all(),
                    "dir": str(library.TRANSCRIPTS_DIR)})


@app.get("/api/library/<key>")
def api_library_entry(key):
    entry = library.get(key)
    if entry is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(entry)


# ---------------------------------------------------------------- cover image

COVER_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _cover_options() -> list[dict]:
    library.ensure_dirs()
    current = _cover_image()
    out = []
    for f in sorted(library.ASSETS_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in COVER_EXTS:
            out.append({
                "name": f.name,
                "size_kb": round(f.stat().st_size / 1024),
                "current": str(f) == current,
            })
    return out


@app.get("/api/cover")
def api_cover():
    current = Path(_cover_image())
    return jsonify({
        "current": current.name if current.is_file() else None,
        "missing": not current.is_file(),
        "options": _cover_options(),
        "dir": str(library.ASSETS_DIR),
    })


@app.get("/api/cover/image/<name>")
def api_cover_image(name):
    """Serve a cover thumbnail. Name only — never an arbitrary path."""
    path = (library.ASSETS_DIR / Path(name).name)
    if not path.is_file() or path.suffix.lower() not in COVER_EXTS:
        return jsonify({"error": "not found"}), 404
    return send_file(path)


@app.post("/api/cover")
def api_cover_set():
    """
    Choose the default cover. Accepts one of:
      {"asset": "name.png"}        pick one already in ~/Tapecut/assets
      {"path": "/local/img.png"}   import a local image
      {"drive": "gdrive:.../x.png"} import from Google Drive
    """
    data = request.get_json(force=True)
    library.ensure_dirs()

    try:
        if data.get("asset"):
            target = library.ASSETS_DIR / Path(data["asset"]).name
            if not target.is_file():
                raise ValueError(f"No such cover image: {target.name}")
        elif data.get("path"):
            src = Path(data["path"]).expanduser()
            if not src.is_file():
                raise ValueError(f"File not found: {src}")
            if src.suffix.lower() not in COVER_EXTS:
                raise ValueError(f"Not an image: {src.suffix} (use png/jpg/webp)")
            target = library.ASSETS_DIR / src.name
            if src.resolve() != target.resolve():
                shutil.copyfile(src, target)
        elif data.get("drive"):
            source = data["drive"].strip()
            if Path(source).suffix.lower() not in COVER_EXTS:
                raise ValueError("Drive path must point at a png/jpg/webp image")
            target = library.ASSETS_DIR / Path(source).name
            drive.copy_to(source, target)
        else:
            raise ValueError("Nothing to set — provide asset, path or drive")
    except (ValueError, drive.DriveError) as e:
        return jsonify({"error": str(e)}), 400

    cfg = library.load_config()
    cfg["cover_image"] = str(target)
    library.save_config(cfg)
    return jsonify({"ok": True, "current": target.name, "options": _cover_options()})


@app.delete("/api/cover/<name>")
def api_cover_delete(name):
    path = library.ASSETS_DIR / Path(name).name
    if not path.is_file():
        return jsonify({"error": "not found"}), 404
    if str(path) == _cover_image():
        return jsonify({"error": "That is the current cover — pick another first."}), 400
    path.unlink()
    return jsonify({"ok": True, "options": _cover_options()})


# ---------------------------------------------------------------- speakers

@app.get("/api/diarize/status")
def api_diarize_status():
    return jsonify({"available": diarize.is_available()})


@app.post("/api/diarize")
def api_diarize():
    """Attach speaker labels to a word list (job). Slow: roughly realtime."""
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    words = data.get("words") or []
    if not words:
        return jsonify({"error": "No transcript to label."}), 400

    def as_int(key):
        v = data.get(key)
        return int(v) if v not in (None, "", 0, "0") else None

    def work():
        labelled = diarize.diarize_words(
            str(path), words,
            num_speakers=as_int("num_speakers"),
            min_speakers=as_int("min_speakers"),
            max_speakers=as_int("max_speakers"),
        )
        library.save(str(path), labelled, data.get("prompt", ""),
                     data.get("source", str(path)), data.get("pause_cuts"),
                     data.get("speaker_names"), data.get("analyses"))
        return {"words": labelled, "speakers": diarize.speaker_list(labelled)}

    return jsonify({"job": _start_job(work)})


# ---------------------------------------------------------------- transcript text

@app.post("/api/text")
def api_text():
    """Render the transcript as txt/md/srt/vtt and return it as a string."""
    data = request.get_json(force=True)
    fmt = (data.get("format") or "txt").lower()
    if fmt not in textexport.FORMATS:
        return jsonify({"error": f"Unsupported format: {fmt}"}), 400
    try:
        text = textexport.render(
            fmt, data.get("words") or [], data.get("title", ""),
            data.get("speaker_names") or {}, bool(data.get("include_cut")),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"format": fmt, "text": text})


@app.post("/api/text/save")
def api_text_save():
    """Write the rendered transcript into ~/Tapecut/exports and return the path."""
    data = request.get_json(force=True)
    fmt = (data.get("format") or "txt").lower()
    if fmt not in textexport.FORMATS:
        return jsonify({"error": f"Unsupported format: {fmt}"}), 400
    stem = _media_stem(data.get("title") or "transcript")
    # text exports are not edited media — name them for what they are
    suffix = str(data.get("suffix") or "")
    if data.get("raw"):
        # already-rendered Markdown (a summary, meeting notes, …)
        text = str(data["raw"])
    else:
        try:
            text = textexport.render(
                fmt, data.get("words") or [], data.get("title", ""),
                data.get("speaker_names") or {}, bool(data.get("include_cut")),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    if not text.strip():
        return jsonify({"error": "Nothing to save — the transcript is empty."}), 400
    out = _unique_output(library.EXPORTS_DIR, stem, fmt, suffix)
    out.write_text(text)
    return jsonify({"output": str(out)})


# ---------------------------------------------------------------- analysis

@app.get("/api/analyse/backend")
def api_analyse_backend():
    return jsonify(summarize.backend_info())


@app.post("/api/analyse")
def api_analyse():
    """Summary / meeting notes / action items / key points (job)."""
    data = request.get_json(force=True)
    kind = data.get("kind", "summary")
    if kind not in summarize.PROMPTS:
        return jsonify({"error": f"Unknown analysis: {kind}"}), 400
    words = data.get("words") or []
    if not words:
        return jsonify({"error": "No transcript to analyse."}), 400

    # analysis always reads the transcript as spoken, cuts included, so removing
    # a filler from the recording never removes content from the notes
    transcript = textexport.to_text(
        words, names=data.get("speaker_names") or {}, include_cut=False)

    def work():
        return summarize.analyse(kind, transcript)

    return jsonify({"job": _start_job(work)})


# ---------------------------------------------------------------- transcription

@app.post("/api/transcribe")
def api_transcribe():
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    prompt = (data.get("prompt") or "").strip() or None
    language = data.get("language") or None
    source = data.get("source", str(path))

    def work():
        words = transcribe(str(path), prompt, language)
        library.save(str(path), words, prompt or "", source)
        return {"words": words}

    return jsonify({"job": _start_job(work)})


@app.post("/api/save")
def api_save():
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    library.save(str(path), data["words"], data.get("prompt", ""),
                 data.get("source", str(path)), data.get("pause_cuts"),
                 data.get("speaker_names"), data.get("analyses"))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- export

def _resolve_media(source: str, name: str) -> Path:
    """
    Find the recording behind a library entry: local cache, its original
    location, the Drive path it came from, or — last resort — a Drive search
    by filename.
    """
    cached = library.CACHE_DIR / name
    if cached.is_file():
        return cached
    if source and Path(source).is_file():
        return Path(source)
    if drive.parse_remote(source):
        return Path(drive.fetch_remote(source))
    found = drive.find_by_name(name)
    if not found:
        raise RuntimeError(
            f"Cannot find the recording for '{name}'. It is not in the cache, "
            "its saved location no longer exists, and it was not found in your "
            "Drive folder."
        )
    return Path(drive.fetch_remote(found))


def _cover_image() -> str:
    """Cover image used when rendering audio-only recordings to MP4."""
    cfg = library.load_config()
    custom = cfg.get("cover_image")
    if custom and Path(custom).is_file():
        return custom
    return str(library.ASSETS_DIR / "youtube_background.png")


def _unique_output(directory: Path, stem: str, fmt: str, suffix: str = "_edited") -> Path:
    library.ensure_dirs()
    out = directory / f"{stem}{suffix}.{fmt}"
    n = 2
    while out.exists():
        out = directory / f"{stem}{suffix}_{n}.{fmt}"
        n += 1
    return out


def _media_stem(title: str) -> str:
    """Filename stem for a text export, with any media extension stripped."""
    name = (title or "transcript").strip()
    for ext in SUPPORTED_FORMATS:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.strip() or "transcript"


def _run_export(path: Path, words: list, pause_cuts, fmt: str,
                prompt: str = "", source: str = "") -> dict:
    """Cut `path` down to the kept ranges and write `fmt`. Returns {"output": ...}."""
    kept = {i for i, w in enumerate(words) if not w.get("deleted")}
    segments = compute_kept_segments(words, kept)
    segments = subtract_ranges(segments, pause_cut_ranges(words, pause_cuts or []))
    if not segments:
        raise ValueError("Everything is deleted — nothing to export.")

    # Drive-sourced recordings export to ~/Tapecut/exports (the cache is
    # temporary); local files export next to the source. Never overwrites.
    out_dir = library.EXPORTS_DIR if library.CACHE_DIR in path.parents else path.parent
    out = _unique_output(out_dir, path.stem, fmt)

    if fmt == "mp4":
        if has_video_stream(str(path)):
            export_video_via_ffmpeg(str(path), segments, str(out))
        else:
            # no picture track (plain audio, or an audio-only .mp4):
            # render the edited audio over the cover image for YouTube
            export_audio_as_video(str(path), segments, str(out), _cover_image())
    else:
        segment = build_edited_audio(str(path), segments)
        if segment is None:
            raise ValueError("Nothing to export.")
        export_audio(segment, str(out))

    library.save(str(path), words, prompt, source or str(path), pause_cuts)
    return {"output": str(out)}


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True)
    try:
        path = _valid_media_path(data.get("path", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    fmt = data.get("format", "mp4")
    if fmt not in {"mp4", "mp3", "wav"}:
        return jsonify({"error": f"Unsupported format: {fmt}"}), 400

    words = data["words"]
    pause_cuts = data.get("pause_cuts") or []
    prompt = data.get("prompt", "")
    source = data.get("source", str(path))

    kept = {i for i, w in enumerate(words) if not w.get("deleted")}
    if not compute_kept_segments(words, kept):
        return jsonify({"error": "Everything is deleted — nothing to export."}), 400

    def work():
        return _run_export(path, words, pause_cuts, fmt, prompt, source)

    return jsonify({"job": _start_job(work)})


@app.post("/api/library/<key>/open")
def api_library_open(key):
    """
    Reopen a stored transcript in the editor, keeping every saved edit.
    Re-downloads the recording from Drive if the cache no longer holds it.
    """
    entry = library.get(key)
    if entry is None:
        return jsonify({"error": "not found"}), 404
    source = entry.get("source", "")
    name = entry.get("media_name", "")

    def work():
        try:
            path = _resolve_media(source, name)
            payload = _open_payload(path, source=source if drive.parse_remote(source) else "")
        except Exception as exc:
            # The recording is gone (moved, renamed, deleted) but the transcript
            # is not — show it anyway so the text stays readable and editable.
            # Playback and export are disabled until the file is found again.
            payload = {
                "path": None, "name": name, "source": source,
                "is_video": False, "audio_in_video_container": False,
                "silent": False, "needs_conversion": False,
                "model_cached": is_model_cached(),
                "media_missing": True, "media_error": str(exc),
            }
        # the library entry is the authority on the edits
        payload["words"] = entry["words"]
        payload["prompt"] = entry.get("prompt", "")
        payload["pause_cuts"] = entry.get("pause_cuts", [])
        return payload

    return jsonify({"job": _start_job(work)})


@app.post("/api/library/<key>/export")
def api_library_export(key):
    """
    Re-export a stored transcript's edit exactly as saved — re-downloading the
    recording from Drive first if it is no longer in the local cache.
    """
    entry = library.get(key)
    if entry is None:
        return jsonify({"error": "not found"}), 404
    fmt = (request.get_json(silent=True) or {}).get("format", "mp4")
    if fmt not in {"mp4", "mp3", "wav"}:
        return jsonify({"error": f"Unsupported format: {fmt}"}), 400

    source = entry.get("source", "")
    name = entry.get("media_name", "")

    def work():
        path = _resolve_media(source, name)
        return _run_export(path, entry["words"], entry.get("pause_cuts", []),
                           fmt, entry.get("prompt", ""), source)

    return jsonify({"job": _start_job(work)})


# ---------------------------------------------------------------- jobs

@app.get("/api/job/<job_id>")
def api_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "unknown job"}), 404
        payload = {
            "status": job["status"],
            "elapsed": round(time.time() - job["started"], 1),
        }
        if job["status"] == "done":
            payload.update(job["result"])
        elif job["status"] == "error":
            payload["error"] = job["error"]
    return jsonify(payload)


if __name__ == "__main__":
    library.ensure_dirs()
    print(f"Tapecut running — open http://{HOST}:{PORT} in your browser")
    app.run(host=HOST, port=PORT, threaded=True)

# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Speaker diarization — "who spoke when" — layered onto an existing transcript.

pyannote via whisperx.diarize.DiarizationPipeline, then assign_word_speakers()
to attach a speaker label to every word. Runs on CPU; the community-1 model is what
whisperX loads by default and is already in the HuggingFace cache.

Needs a HuggingFace token (the pyannote models are gated). It is read from, in
order: TAPECUT_HF_TOKEN, HF_TOKEN, the "hf_token" key in ~/Tapecut/config.json,
or an .env file named by "hf_token_env_file" there — so if you already keep a
token in some other project's .env, you can point at it instead of copying it.
"""
import gc
import json
import os
from pathlib import Path

from core import library

_pipeline = None


class DiarizationError(RuntimeError):
    pass


def _read_env_file(path: Path, key: str) -> str | None:
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def hf_token() -> str | None:
    for var in ("TAPECUT_HF_TOKEN", "HF_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    cfg = library.load_config()
    token = cfg.get("hf_token")
    if token:
        return token
    env_file = cfg.get("hf_token_env_file")
    if env_file:
        return _read_env_file(Path(env_file).expanduser(), "HF_TOKEN")
    return None


def is_available() -> bool:
    return bool(hf_token())


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    token = hf_token()
    if not token:
        raise DiarizationError(
            "No HuggingFace token found. Speaker labels need one because the "
            "pyannote models are gated. Set HF_TOKEN, or add \"hf_token\" to "
            "~/Tapecut/config.json."
        )
    try:
        from whisperx.diarize import DiarizationPipeline
    except ImportError as exc:
        raise DiarizationError(f"whisperx diarization unavailable: {exc}")
    try:
        _pipeline = DiarizationPipeline(token=token, device="cpu")
    except Exception as exc:
        raise DiarizationError(
            "Could not load the diarization model. If this is the first run the "
            "model has to download, and the pyannote terms must be accepted on "
            f"huggingface.co with this token.\n{exc}"
        )
    return _pipeline


def diarize_words(
    audio_path: str,
    words: list[dict],
    num_speakers: int | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
) -> list[dict]:
    """
    Attach a "speaker" key to each word, in place, and return the list.
    Words pyannote cannot attribute keep whatever speaker they already had, so
    a partial result never wipes existing labels.
    """
    if not words:
        return words
    import whisperx
    from whisperx.diarize import assign_word_speakers

    pipeline = _load_pipeline()
    audio = whisperx.load_audio(audio_path)
    try:
        segments = pipeline(
            audio, num_speakers=num_speakers,
            min_speakers=min_speakers, max_speakers=max_speakers,
        )
    except Exception as exc:
        raise DiarizationError(f"Diarization failed: {exc}")

    # assign_word_speakers works on whisperX's segment structure; wrap the flat
    # word list as a single segment so we can reuse it unchanged
    payload = {"segments": [{
        "start": words[0]["start"], "end": words[-1]["end"],
        "text": " ".join(w["word"] for w in words),
        "words": words,
    }]}
    result = assign_word_speakers(segments, payload)

    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            if w.get("speaker"):
                w["speaker"] = str(w["speaker"])

    gc.collect()
    return words


def speaker_list(words: list[dict]) -> list[str]:
    """Distinct speakers in order of first appearance."""
    seen: list[str] = []
    for w in words:
        s = w.get("speaker")
        if s and s not in seen:
            seen.append(s)
    return seen


def group_by_speaker(words: list[dict], names: dict | None = None) -> list[dict]:
    """
    Collapse the word list into consecutive same-speaker blocks:
        [{"speaker": "SPEAKER_00", "label": "Teodora", "start", "end",
          "first_index", "words": [...]}, ...]
    Used for display and for text export.
    """
    names = names or {}
    blocks: list[dict] = []
    for i, w in enumerate(words):
        spk = w.get("speaker") or ""
        if blocks and blocks[-1]["speaker"] == spk:
            blocks[-1]["words"].append(w)
            blocks[-1]["end"] = w["end"]
        else:
            blocks.append({
                "speaker": spk,
                "label": names.get(spk, spk),
                "start": w["start"], "end": w["end"],
                "first_index": i,
                "words": [w],
            })
    return blocks

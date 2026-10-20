# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Transcription engine: whisperX (faster-whisper large-v3 + forced alignment).

Chosen over mlx-whisper (used previously) because, on real meditation
recordings:
  - VAD segmentation: silent stretches produce NO output instead of
    hallucinated loops ("Thank you. Thank you. …")
  - `hotwords`: the vocabulary list boosts recognition of Pali/Sanskrit terms
    without consuming Whisper's 224-token prompt budget
  - wav2vec2 forced alignment gives more precise word timestamps (better cuts)

CPU + CTranslate2 float32 — the combination this has been tested against.
Models are cached at module level — the first transcription in a session loads
large-v3 (~20 s), subsequent ones reuse it if the prompt didn't change.
"""
import gc
import os
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

# This Mac's system proxy settings contain a malformed host (embedded newline)
# that crashes Python's proxy handling (requests/urllib/httpx) whenever a
# library phones home — e.g. HuggingFace model downloads. Setting no_proxy
# makes getproxies_environment() non-empty, so the broken macOS sysconf proxies
# are never read, and '*' bypasses proxying entirely (direct connections work
# fine on this machine).
os.environ.setdefault("no_proxy", "*")
os.environ.setdefault("NO_PROXY", "*")

MODEL_NAME = "large-v3"
DEVICE = "cpu"            # CTranslate2 has no Metal backend; CPU is the way on macOS
COMPUTE_TYPE = "float32"  # int8 is faster but has been less reliable here
BATCH_SIZE = 2
MODEL_CACHE = Path.home() / ".cache" / "huggingface" / "hub"

# whisperx decodes via ffmpeg, so video containers work directly too
SUPPORTED_FORMATS = {
    # audio (ffmpeg decodes all of these)
    ".mp3", ".wav", ".m4a", ".flac", ".opus", ".ogg", ".oga", ".aac", ".aiff", ".aif", ".wma",
    # video containers
    ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi",
}

# Whisper imitates the style of its initial_prompt: prime it with hesitant,
# stumbling speech and it stops silently tidying disfluencies away. That matters
# here — a repetition Whisper omits is audio the editor can never cut, because
# there is no word on screen to click.
VERBATIM_PRIMER = (
    "Um, so, uh, I— I mean, like, you know, it's— it's kind of, uh, hmm, "
    "well, the the thing is, um, yeah."
)

_asr_cache: dict = {"key": None, "model": None}
_align_cache: dict = {}   # language code -> (align_model, metadata)


def is_model_cached() -> bool:
    """Check if model weights are already on disk so we can warn before download."""
    return any(MODEL_CACHE.glob("models--Systran--faster-whisper-large-v3"))


def _load_asr_model(initial_prompt: str | None, hotwords: str | None):
    import whisperx
    key = (initial_prompt, hotwords)
    if _asr_cache["key"] == key and _asr_cache["model"] is not None:
        return _asr_cache["model"]
    _asr_cache["model"] = None
    gc.collect()
    asr_options = {"initial_prompt": initial_prompt, "hotwords": hotwords}
    model = whisperx.load_model(
        MODEL_NAME, DEVICE, compute_type=COMPUTE_TYPE, asr_options=asr_options
    )
    _asr_cache.update(key=key, model=model)
    return model


def transcribe(audio_path: str, initial_prompt: str | None = None,
               language: str = "en", verbatim: bool = True) -> list[dict]:
    """
    Synchronous transcription. Returns a flat list of word dicts:
        [{"word": str, "start": float, "end": float, "probability": float,
          "deleted": False}, ...]

    The vocabulary hint goes to faster-whisper `hotwords` ONLY — it boosts those
    words' log-probabilities without ever entering the token stream. It must
    never be put in `initial_prompt`: whisperX injects that into every 30 s
    chunk, and Whisper will happily transcribe a comma-separated list as if it
    were speech. Doing that once produced 2,747 echoes of the hint across a
    batch of recordings — the word list, recited mid-sentence, again and again.
    `initial_prompt` therefore carries only the verbatim primer, which is a
    natural sentence and leaks far less.

    Language defaults to English; pass None/"" for auto-detection.
    """
    import whisperx

    vocab = (initial_prompt or "").strip()
    # hotwords: the user's terms, boosted but never emitted
    hotwords = ", ".join(t.strip() for t in vocab.replace("\n", ",").split(",") if t.strip()) or None
    # initial_prompt: style only, never the word list
    prompt = VERBATIM_PRIMER if verbatim else None

    model = _load_asr_model(prompt, hotwords)
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(
        audio, batch_size=BATCH_SIZE, language=language or None, chunk_size=30
    )

    lang = result["language"]
    if lang not in _align_cache:
        _align_cache[lang] = whisperx.load_align_model(language_code=lang, device=DEVICE)
    model_a, metadata = _align_cache[lang]
    aligned = whisperx.align(
        result["segments"], model_a, metadata, audio, DEVICE,
        return_char_alignments=False,
    )

    words: list[dict] = []
    prev_end = 0.0
    for segment in aligned.get("segments", []):
        for w in segment.get("words", []):
            text = w.get("word", "").strip()
            if not text:
                continue
            # alignment occasionally can't place a word (numbers, non-speech):
            # give it a tiny slot right after the previous word
            start = float(w.get("start", prev_end))
            end = float(w.get("end", start + 0.3))
            words.append({
                "word": text,
                "start": start,
                "end": max(end, start),
                "probability": float(w.get("score", 1.0)),
                "deleted": False,
            })
            prev_end = words[-1]["end"]

    words = drop_prompt_echo(words, [prompt, hotwords])
    words = collapse_loops(words)
    gc.collect()
    return words


def _norm_token(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def drop_prompt_echo(words: list[dict], prompts, min_run: int = 5) -> list[dict]:
    """
    Remove runs where Whisper transcribed the prompt instead of the speech.

    Only a run of `min_run`+ words that follows the prompt's own word order is
    dropped, so a real mention of one prompt word ("the HELIOS dataset") is
    always kept — people say those words, they just never recite the whole list.
    """
    sequences = []
    for p in prompts:
        toks = [_norm_token(t) for t in (p or "").split() if _norm_token(t)]
        if len(toks) >= min_run:
            sequences.append(toks)
    if not sequences or not words:
        return words

    drop = set()
    norm = [_norm_token(w["word"]) for w in words]
    for seq in sequences:
        positions = {tok: i for i, tok in enumerate(seq)}
        i = 0
        while i < len(norm):
            if norm[i] not in positions:
                i += 1
                continue
            # walk forward while the words keep advancing through the prompt
            j, last = i, positions[norm[i]] - 1
            run = []
            while j < len(norm) and norm[j] in positions and positions[norm[j]] > last:
                last = positions[norm[j]]
                run.append(j)
                j += 1
            if len(run) >= min_run:
                drop.update(run)
                i = j
            else:
                i += 1
    return [w for k, w in enumerate(words) if k not in drop]


def collapse_loops(words: list[dict], max_repeats: int = 2, max_phrase: int = 6) -> list[dict]:
    """
    Collapse Whisper's stuck-loop output — the same short phrase emitted over
    and over ("Um, so, um, yeah. Um, so, um, yeah. …"). It happens on quiet or
    low-confidence audio and is model noise, not speech.

    A phrase must repeat more than `max_repeats` times back-to-back before any
    copy is dropped, and the first `max_repeats` are always kept, so deliberate
    repetition ("very, very", "more and more") survives untouched.
    """
    if not words:
        return words

    norm = [_norm_token(w["word"]) for w in words]
    drop = set()
    i = 0
    while i < len(norm):
        for size in range(max_phrase, 0, -1):          # longest phrase first
            block = norm[i:i + size]
            if len(block) < size or not any(block):
                continue
            reps = 1
            j = i + size
            while norm[j:j + size] == block:
                reps += 1
                j += size
            if reps > max_repeats:
                drop.update(range(i + size * max_repeats, j))
                i = j
                break
        else:
            i += 1
            continue
        if not drop:
            i += 1
    return [w for k, w in enumerate(words) if k not in drop]


class TranscriberThread(QThread):
    """Run transcription off the main thread so the UI stays responsive."""

    started_transcription = pyqtSignal()
    progress = pyqtSignal(int, int)   # (segments_done, total_segments) — best-effort
    # note: named `done`, not `finished`, to avoid shadowing QThread.finished
    done = pyqtSignal(list)            # word list
    error = pyqtSignal(str)

    def __init__(self, audio_path: str, initial_prompt: str | None = None, language: str = "en"):
        super().__init__()
        self.audio_path = audio_path
        self.initial_prompt = initial_prompt
        self.language = language

    def run(self):
        self.started_transcription.emit()
        try:
            words = transcribe(self.audio_path, self.initial_prompt, self.language)
            self.done.emit(words)
        except Exception as exc:
            self.error.emit(str(exc))

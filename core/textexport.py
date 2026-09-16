# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Transcript → text. Plain text, Markdown, SRT and WebVTT.

Speaker labels appear wherever they exist, and cut words are handled by the
`include_cut` flag: keep them (bracketed, for a verbatim record) or drop them
(for the transcript of the edited recording).
"""
from pathlib import Path

from core.diarize import group_by_speaker

FORMATS = {"txt", "md", "srt", "vtt"}


def _ts(seconds: float, comma: bool = False) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _clock(seconds: float) -> str:
    m, s = divmod(int(max(0.0, seconds)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _visible(words: list[dict], include_cut: bool) -> list[dict]:
    return words if include_cut else [w for w in words if not w.get("deleted")]


def _word_text(w: dict, include_cut: bool) -> str:
    # cut words are bracketed so a verbatim export still shows what was removed
    return f"[{w['word']}]" if include_cut and w.get("deleted") else w["word"]


def to_text(words, title="", names=None, include_cut=False, timestamps=False) -> str:
    words = _visible(words, include_cut)
    if not words:
        return ""
    lines = [title, "=" * len(title), ""] if title else []
    for block in group_by_speaker(words, names):
        text = " ".join(_word_text(w, include_cut) for w in block["words"])
        stamp = f"[{_clock(block['start'])}] " if timestamps else ""
        if block["speaker"]:
            lines.append(f"{stamp}{block['label']}: {text}")
        else:
            lines.append(f"{stamp}{text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_markdown(words, title="", names=None, include_cut=False, timestamps=True) -> str:
    words = _visible(words, include_cut)
    if not words:
        return ""
    out = [f"# {title}" if title else "# Transcript", ""]
    if include_cut:
        out += ["*Words in [brackets] were cut from the edited recording.*", ""]
    for block in group_by_speaker(words, names):
        text = " ".join(_word_text(w, include_cut) for w in block["words"])
        stamp = f" <sub>{_clock(block['start'])}</sub>" if timestamps else ""
        if block["speaker"]:
            out.append(f"**{block['label']}**{stamp}")
            out.append("")
            out.append(text)
        else:
            out.append(f"{stamp.strip() + ' ' if stamp else ''}{text}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def to_srt(words, names=None, include_cut=False, max_chars=84) -> str:
    return _captions(words, names, include_cut, max_chars, vtt=False)


def to_vtt(words, names=None, include_cut=False, max_chars=84) -> str:
    return "WEBVTT\n\n" + _captions(words, names, include_cut, max_chars, vtt=True)


def _captions(words, names, include_cut, max_chars, vtt) -> str:
    """Wrap words into caption cues, breaking on speaker change and length."""
    words = _visible(words, include_cut)
    if not words:
        return ""
    names = names or {}
    cues, cur = [], []
    for w in words:
        same_speaker = not cur or cur[-1].get("speaker") == w.get("speaker")
        length = sum(len(x["word"]) + 1 for x in cur)
        if cur and (not same_speaker or length + len(w["word"]) > max_chars):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)

    out = []
    for i, cue in enumerate(cues, 1):
        speaker = cue[0].get("speaker")
        prefix = f"{names.get(speaker, speaker)}: " if speaker else ""
        text = prefix + " ".join(_word_text(w, include_cut) for w in cue)
        out.append(str(i))
        out.append(f"{_ts(cue[0]['start'], not vtt)} --> {_ts(cue[-1]['end'], not vtt)}")
        out.append(text)
        out.append("")
    return "\n".join(out)


def render(fmt: str, words, title="", names=None, include_cut=False) -> str:
    fmt = fmt.lower()
    if fmt == "txt":
        return to_text(words, title, names, include_cut)
    if fmt == "md":
        return to_markdown(words, title, names, include_cut)
    if fmt == "srt":
        return to_srt(words, names, include_cut)
    if fmt == "vtt":
        return to_vtt(words, names, include_cut)
    raise ValueError(f"Unsupported text format: {fmt}")

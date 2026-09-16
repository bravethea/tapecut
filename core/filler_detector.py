# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import re

# Vocalized fillers matched as a pattern, so elongated spellings are caught
# too: uh/uhh/uhhh, um/umm, uhm, ah/ahh/ahm, er/erm, eh, hm/hmm, mm/mhm.
FILLER_PATTERN = re.compile(r"^(u+[hm]+|a+h+m*|e+r+m*|e+h+|h+m+|m+h+m*|mm+)$")

FILLER_WORDS = {
    "like", "you know", "basically", "literally",
    "actually", "so", "right", "okay", "well", "i mean",
    "sort of", "kind of", "i guess", "or whatever",
}


def is_filler(text: str) -> bool:
    """True if the normalized word is a filler (pattern or word list)."""
    return bool(FILLER_PATTERN.match(text)) or text in FILLER_WORDS

_PUNCT = re.compile(r"[^\w\s]")


def _normalize(text: str) -> str:
    return _PUNCT.sub("", text).strip().lower()


def find_fillers(words: list[dict]) -> list[int]:
    """
    Return indices of words whose normalized text is in FILLER_WORDS.
    Case-insensitive, punctuation-stripped.
    Multi-word fillers (e.g. "you know") are matched across adjacent words.
    """
    indices: list[int] = []
    i = 0
    while i < len(words):
        # Try two-word filler first
        if i + 1 < len(words):
            bigram = _normalize(words[i]["word"]) + " " + _normalize(words[i + 1]["word"])
            if bigram in FILLER_WORDS:
                indices.extend([i, i + 1])
                i += 2
                continue
        if is_filler(_normalize(words[i]["word"])):
            indices.append(i)
        i += 1
    return indices


def find_long_silences(
    words: list[dict],
    threshold_sec: float = 1.0,
    trim_to_sec: float = 0.5,
) -> list[dict]:
    """
    Find gaps between word end and next word start that exceed threshold_sec.
    Returns a list of dicts describing each gap and the proposed trim.
    """
    gaps = []
    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap > threshold_sec:
            gaps.append({
                "after_word_index": i,
                "gap_sec": round(gap, 3),
                "trim_to_sec": trim_to_sec,
                "original_end": words[i]["end"],
                "next_start": words[i + 1]["start"],
            })
    return gaps

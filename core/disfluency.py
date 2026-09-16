# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Disfluency detection: repeated words/phrases and stutters.

Whisper tends to tidy speech up, but when it *does* transcribe a stumble
("the the", "I- I mean", "wh- what") the repeated words are real audio you
probably want cut. This module finds them so the UI can cross them out for
review — visible, and restorable with a single click, never silently dropped.

Two heuristics, both deliberately conservative:

* repetition — the same 1–3 word block said twice in a row, with only a short
  gap between the two. The FIRST block is marked; the cleaner second reading is
  what survives. The gap limit matters for meditation recordings, where a
  deliberate "breathe … breathe" seconds apart must not be treated as a stumble.
* stutter — a truncated fragment right before the word it becomes: an explicit
  "th-" hyphen form, or a 2–3 letter token that prefixes the next word.
"""
import re

MAX_REPEAT_GAP_SEC = 0.8   # longer than this and the repetition looks intentional
MAX_STUTTER_GAP_SEC = 0.8
MAX_PHRASE_LEN = 3         # look for repeated blocks up to this many words

_PUNCT = re.compile(r"[^\w\s']")

# short words that legitimately precede a word they happen to prefix
# ("a apple", "in individual") — never treat these as stutter fragments
_COMMON_SHORT = {
    "a", "i", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is",
    "it", "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we",
    "the", "and", "for", "you", "our", "out", "all", "can", "not", "but",
}


def _norm(text: str) -> str:
    return _PUNCT.sub("", text).strip().lower()


def _ends_sentence(text: str) -> bool:
    return text.strip().endswith((".", "!", "?", "…"))


def find_repetitions(words: list[dict]) -> list[int]:
    """
    Indices of words belonging to an immediately repeated block.
    Longest blocks are matched first so "I mean I mean" is caught as a phrase
    rather than as two single-word repeats.

    Two things are deliberately NOT treated as stumbles:
      * a repeat across a sentence boundary — "just settling in. In fact …"
      * a chain that keeps going — "more and more and more" is rhetoric, and a
        real stumble repeats once, not indefinitely.
    """
    n = len(words)
    marked: set[int] = set()

    for size in range(MAX_PHRASE_LEN, 0, -1):
        i = 0
        while i + 2 * size <= n:
            first = [_norm(w["word"]) for w in words[i:i + size]]
            second = [_norm(w["word"]) for w in words[i + size:i + 2 * size]]
            if (all(first) and first == second
                    and not any(k in marked for k in range(i, i + 2 * size))):
                gap = words[i + size]["start"] - words[i + size - 1]["end"]
                crosses_sentence = _ends_sentence(words[i + size - 1]["word"])
                # does the same block keep repeating around the pair? check
                # both directions — "more and more and more" aligns as either
                # "[more and][more and] more" or "more [and more][and more]"
                after = i + 2 * size
                chain = (
                    (after < n and _norm(words[after]["word"]) == first[0])
                    or (i > 0 and _norm(words[i - 1]["word"]) == first[-1])
                )
                if gap <= MAX_REPEAT_GAP_SEC and not crosses_sentence and not chain:
                    marked.update(range(i, i + size))   # drop the first pass
                    i += 2 * size
                    continue
            i += 1

    return sorted(marked)


def find_stutters(words: list[dict]) -> list[int]:
    """Indices of truncated fragments that precede the full word."""
    marked: list[int] = []
    for i in range(len(words) - 1):
        raw = words[i]["word"].strip()
        cur, nxt = _norm(raw), _norm(words[i + 1]["word"])
        if not cur or not nxt or cur == nxt:
            continue
        if words[i + 1]["start"] - words[i]["end"] > MAX_STUTTER_GAP_SEC:
            continue

        hyphenated = raw.rstrip(".,!?").endswith("-")
        fragment = (
            2 <= len(cur) <= 3
            and cur not in _COMMON_SHORT
            and nxt.startswith(cur)
            and len(nxt) > len(cur)
        )
        if hyphenated or fragment:
            marked.append(i)
    return marked


def find_all(words: list[dict]) -> dict[str, list[int]]:
    """
    All disfluency indices by category. Repetition wins over stutter when both
    match, so an index is never reported twice.
    """
    repeats = find_repetitions(words)
    stutters = [i for i in find_stutters(words) if i not in set(repeats)]
    return {"repetition": repeats, "stutter": stutters}

# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
from pydub import AudioSegment

CROSSFADE_MS = 30  # ms of crossfade between joined segments to avoid clicks

# pause trimming: a "cut" pause between words keeps this much breathing room
# on each side of the gap (so a 6 s pause becomes ~0.5 s, not a hard splice)
PAUSE_KEEP_SEC = 0.25
PAUSE_MIN_GAP_SEC = 1.0  # gaps shorter than this are never offered for trimming


def _kept_runs(kept_indices: set[int]) -> list[list[int]]:
    """Group kept indices into maximal contiguous runs."""
    runs: list[list[int]] = []
    for idx in sorted(kept_indices):
        if runs and idx == runs[-1][-1] + 1:
            runs[-1].append(idx)
        else:
            runs.append([idx])
    return runs


def compute_kept_segments(words: list[dict], kept_indices: set[int]) -> list[tuple[float, float]]:
    """
    Given a flat word list and the set of indices to KEEP, return a merged list of
    (start_sec, end_sec) time ranges.  Contiguous kept words are merged into one range.
    Returns [] if kept_indices is empty.

    A run spans from its first kept word's start to its last kept word's end, so
    deleting words also drops the silence either side of them — which is what
    you want when cutting a whole passage out. (A variant that preserved that
    silence was tried and reverted: it left dead air around every cut.)
    """
    if not kept_indices:
        return []

    sorted_indices = sorted(kept_indices)
    segments: list[tuple[float, float]] = []
    run_start = words[sorted_indices[0]]["start"]
    run_end = words[sorted_indices[0]]["end"]

    for idx in sorted_indices[1:]:
        w = words[idx]
        if idx - 1 in kept_indices:
            # contiguous with previous kept word — extend current run
            run_end = w["end"]
        else:
            segments.append((run_start, run_end))
            run_start = w["start"]
            run_end = w["end"]

    segments.append((run_start, run_end))
    return segments


def build_edited_audio(source_path: str, segments: list[tuple[float, float]]) -> AudioSegment | None:
    """
    Slice source audio at the given time ranges and concatenate with a short crossfade.
    Returns None if segments is empty.
    """
    if not segments:
        return None

    source = AudioSegment.from_file(source_path)
    chunks: list[AudioSegment] = []

    for start_sec, end_sec in segments:
        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)
        chunks.append(source[start_ms:end_ms])

    result = chunks[0]
    for chunk in chunks[1:]:
        result = result.append(chunk, crossfade=CROSSFADE_MS)

    return result


def kept_indices_from_words(words: list[dict]) -> set[int]:
    """Convenience: derive kept_indices from the `deleted` flag on each word."""
    return {i for i, w in enumerate(words) if not w.get("deleted", False)}


def pause_cut_ranges(words: list[dict], pause_indices) -> list[tuple[float, float]]:
    """
    Convert trimmed-pause markers into time ranges to remove.
    Each index i means "the gap after word i is trimmed": the removed range is
    [word[i].end + PAUSE_KEEP, word[i+1].start - PAUSE_KEEP].
    """
    cuts = []
    for i in pause_indices:
        if not (0 <= i < len(words) - 1):
            continue
        start = words[i]["end"] + PAUSE_KEEP_SEC
        end = words[i + 1]["start"] - PAUSE_KEEP_SEC
        if end > start:
            cuts.append((start, end))
    cuts.sort()
    return cuts


def subtract_ranges(
    segments: list[tuple[float, float]], cuts: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """Remove the given (sorted) cut ranges from the kept segments."""
    if not cuts:
        return segments
    result = []
    for seg_start, seg_end in segments:
        pieces = [(seg_start, seg_end)]
        for cut_start, cut_end in cuts:
            next_pieces = []
            for s, e in pieces:
                if cut_end <= s or cut_start >= e:
                    next_pieces.append((s, e))
                    continue
                if cut_start > s:
                    next_pieces.append((s, cut_start))
                if cut_end < e:
                    next_pieces.append((cut_end, e))
            pieces = next_pieces
        result.extend(pieces)
    return [p for p in result if p[1] > p[0]]


def build_edited_timeline(
    words: list[dict], kept_indices: set[int]
) -> list[tuple[float, float, int]]:
    """
    Map each kept word to its time range in the EDITED audio.
    Returns [(edited_start, edited_end, word_index), ...] sorted by edited_start.
    Accounts for the crossfade overlap at each segment join so the playhead
    highlight does not drift on heavily edited files.
    """
    if not kept_indices:
        return []

    crossfade_sec = CROSSFADE_MS / 1000.0
    timeline: list[tuple[float, float, int]] = []

    # walk the same segments the export uses, so the playhead cannot drift
    # away from what is actually rendered
    offset = 0.0
    for (seg_start, seg_end), run in zip(
        compute_kept_segments(words, kept_indices), _kept_runs(kept_indices)
    ):
        for idx in run:
            w = words[idx]
            timeline.append((
                offset + w["start"] - seg_start,
                offset + w["end"] - seg_start,
                idx,
            ))
        # each join consumes one crossfade of overlap
        offset += (seg_end - seg_start) - crossfade_sec

    return timeline


def word_index_at_edited_time(
    timeline: list[tuple[float, float, int]], t: float
) -> int:
    """Given the edited timeline, return the word index at edited time t (or -1)."""
    if not timeline:
        return -1
    lo, hi = 0, len(timeline) - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if timeline[mid][0] <= t:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return timeline[best][2] if best >= 0 else -1

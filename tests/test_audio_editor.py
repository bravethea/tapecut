# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import pytest
from core.audio_editor import (
    compute_kept_segments, build_edited_timeline, word_index_at_edited_time,
    pause_cut_ranges, subtract_ranges, CROSSFADE_MS, PAUSE_KEEP_SEC,
)


def make_words(*pairs):
    """Build a minimal word list from (start, end) pairs."""
    return [{"word": f"w{i}", "start": s, "end": e, "deleted": False}
            for i, (s, e) in enumerate(pairs)]


class TestComputeKeptSegments:
    # NOTE: contiguous kept words are MERGED into one range so that natural
    # pauses between words are preserved (critical for meditation recordings —
    # only explicitly deleted words create cuts).

    def test_all_kept(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        segs = compute_kept_segments(words, {0, 1, 2})
        assert segs == [(0.0, 1.5)]

    def test_all_deleted(self):
        words = make_words((0.0, 0.5), (0.6, 1.0))
        assert compute_kept_segments(words, set()) == []

    # A cut runs from the previous kept word's end to the next kept word's
    # start, so the silence either side of the deleted words goes with them.

    def test_first_deleted(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        segs = compute_kept_segments(words, {1, 2})
        assert segs == [(0.6, 1.5)]

    def test_last_deleted(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        segs = compute_kept_segments(words, {0, 1})
        assert segs == [(0.0, 1.0)]

    def test_middle_deleted(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        segs = compute_kept_segments(words, {0, 2})
        assert segs == [(0.0, 0.5), (1.1, 1.5)]

    def test_contiguous_deletions_yield_single_gap(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5), (1.6, 2.0))
        # words 1 and 2 deleted → only 0 and 3 kept, non-contiguous
        segs = compute_kept_segments(words, {0, 3})
        assert len(segs) == 2

    def test_contiguous_kept_merged(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        # all kept → one continuous range, inter-word pauses preserved
        segs = compute_kept_segments(words, {0, 1, 2})
        assert len(segs) == 1

    def test_single_word_kept(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        segs = compute_kept_segments(words, {1})
        assert segs == [(0.6, 1.0)]

    def test_empty_word_list(self):
        assert compute_kept_segments([], set()) == []


class TestPauseTrimming:
    def test_pause_cut_ranges(self):
        # 5-second gap between word 0 and word 1
        words = make_words((0.0, 1.0), (6.0, 7.0))
        cuts = pause_cut_ranges(words, [0])
        assert cuts == [(1.0 + PAUSE_KEEP_SEC, 6.0 - PAUSE_KEEP_SEC)]

    def test_tiny_gap_yields_no_cut(self):
        words = make_words((0.0, 1.0), (1.2, 2.0))  # 0.2 s gap < 2*PAUSE_KEEP
        assert pause_cut_ranges(words, [0]) == []

    def test_out_of_range_indices_ignored(self):
        words = make_words((0.0, 1.0), (6.0, 7.0))
        assert pause_cut_ranges(words, [-1, 1, 99]) == []

    def test_subtract_middle(self):
        segs = [(0.0, 10.0)]
        assert subtract_ranges(segs, [(4.0, 6.0)]) == [(0.0, 4.0), (6.0, 10.0)]

    def test_subtract_multiple_and_untouched_segments(self):
        segs = [(0.0, 10.0), (20.0, 30.0)]
        cuts = [(2.0, 3.0), (8.0, 9.0)]
        assert subtract_ranges(segs, cuts) == [
            (0.0, 2.0), (3.0, 8.0), (9.0, 10.0), (20.0, 30.0)]

    def test_subtract_nothing(self):
        segs = [(0.0, 5.0)]
        assert subtract_ranges(segs, []) == segs

    def test_pause_inside_deleted_region_is_noop(self):
        # cut range falls entirely outside kept segments
        segs = [(0.0, 1.0)]
        assert subtract_ranges(segs, [(2.0, 3.0)]) == [(0.0, 1.0)]


class TestEditedTimeline:
    def test_no_cuts_timeline_matches_original(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        tl = build_edited_timeline(words, {0, 1, 2})
        assert tl == [(0.0, 0.5, 0), (0.6, 1.0, 1), (1.1, 1.5, 2)]

    def test_cut_shifts_later_words(self):
        # delete word 1 (0.6–1.0); word 2 should start right after word 0's run,
        # minus the crossfade overlap
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        tl = build_edited_timeline(words, {0, 2})
        crossfade = CROSSFADE_MS / 1000.0
        assert tl[0] == (0.0, 0.5, 0)
        ed_start, ed_end, idx = tl[1]
        assert idx == 2
        assert ed_start == pytest.approx(0.5 - crossfade)
        assert ed_end == pytest.approx(0.9 - crossfade)

    def test_timeline_matches_segment_durations(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5), (1.6, 2.0))
        kept = {0, 2, 3}
        tl = build_edited_timeline(words, kept)
        segs = compute_kept_segments(words, kept)
        crossfade = CROSSFADE_MS / 1000.0
        total = sum(e - s for s, e in segs) - crossfade * (len(segs) - 1)
        assert tl[-1][1] <= total + 1e-9

    def test_empty(self):
        assert build_edited_timeline([], set()) == []

    def test_lookup(self):
        words = make_words((0.0, 0.5), (0.6, 1.0), (1.1, 1.5))
        tl = build_edited_timeline(words, {0, 1, 2})
        assert word_index_at_edited_time(tl, 0.1) == 0
        assert word_index_at_edited_time(tl, 0.7) == 1
        assert word_index_at_edited_time(tl, 1.4) == 2
        assert word_index_at_edited_time([], 1.0) == -1

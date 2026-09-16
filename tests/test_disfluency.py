# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import pytest
from core.disfluency import find_repetitions, find_stutters, find_all


def mk(words, gap=0.1, dur=0.3):
    """Word dicts with a fixed gap between them."""
    out, t = [], 0.0
    for w in words:
        out.append({"word": w, "start": t, "end": t + dur})
        t += dur + gap
    return out


class TestRepetitions:
    def test_single_word_repeat_marks_first(self):
        words = mk(["the", "the", "cat"])
        assert find_repetitions(words) == [0]

    def test_phrase_repeat_marks_first_block(self):
        words = mk(["I", "mean", "I", "mean", "yes"])
        assert find_repetitions(words) == [0, 1]

    def test_no_repeat(self):
        assert find_repetitions(mk(["a", "clear", "sentence"])) == []

    def test_long_pause_is_intentional(self):
        # "breathe … breathe" seconds apart is deliberate, not a stumble
        words = [{"word": "breathe", "start": 0.0, "end": 1.0},
                 {"word": "breathe", "start": 5.0, "end": 6.0}]
        assert find_repetitions(words) == []

    def test_sentence_boundary_not_a_stumble(self):
        # "just settling in. In fact …"
        assert find_repetitions(mk(["settling", "in.", "In", "fact"])) == []

    def test_rhetorical_chain_preserved(self):
        # "more and more and more" is rhetoric; a stumble repeats once
        assert find_repetitions(mk(["feeling", "more", "and", "more", "and", "more"])) == []

    def test_case_and_punctuation_insensitive(self):
        assert find_repetitions(mk(["So,", "so", "then"])) == [0]

    def test_empty(self):
        assert find_repetitions([]) == []


class TestStutters:
    @pytest.mark.parametrize("pair", [["wh-", "what"], ["th", "the"], ["st", "stop"]])
    def test_fragments_detected(self, pair):
        assert 0 in find_stutters(mk(pair + ["now"]))

    def test_hyphenated_repeat_counts_as_repetition(self):
        # "I- I" normalises to the same word twice, so it is reported as a
        # repetition rather than a stutter — either way it gets crossed out
        res = find_all(mk(["I-", "I", "mean"]))
        assert 0 in res["repetition"] + res["stutter"]

    @pytest.mark.parametrize("pair", [["a", "apple"], ["in", "individual"], ["to", "total"],
                                      ["the", "there"], ["so", "solid"]])
    def test_common_words_not_fragments(self, pair):
        assert find_stutters(mk(pair + ["now"])) == []

    def test_gap_too_long(self):
        words = [{"word": "wh-", "start": 0.0, "end": 0.3},
                 {"word": "what", "start": 3.0, "end": 3.4}]
        assert find_stutters(words) == []


class TestFindAll:
    def test_categories_do_not_overlap(self):
        words = mk(["I-", "I", "mean", "the", "the", "end"])
        res = find_all(words)
        assert not set(res["repetition"]) & set(res["stutter"])

    def test_shape(self):
        res = find_all(mk(["one", "two"]))
        assert set(res) == {"repetition", "stutter"}

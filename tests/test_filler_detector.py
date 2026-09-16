# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import pytest
from core.filler_detector import find_fillers, is_filler


def make_words(*texts):
    return [{"word": t, "start": float(i), "end": float(i) + 0.3} for i, t in enumerate(texts)]


class TestFindFillers:
    def test_basic_filler(self):
        words = make_words("um", "hello", "world")
        assert find_fillers(words) == [0]

    def test_case_insensitive(self):
        words = make_words("UM", "Hello")
        assert find_fillers(words) == [0]

    def test_no_fillers(self):
        words = make_words("hello", "world")
        assert find_fillers(words) == []

    def test_multiple_fillers(self):
        words = make_words("um", "hello", "uh", "world")
        assert find_fillers(words) == [0, 2]

    def test_two_word_filler(self):
        words = make_words("you", "know", "the", "answer")
        result = find_fillers(words)
        assert 0 in result and 1 in result

    def test_punctuation_stripped(self):
        words = make_words("um,", "hello")
        assert find_fillers(words) == [0]

    def test_filler_at_end(self):
        words = make_words("hello", "world", "uh")
        assert find_fillers(words) == [2]

    def test_all_fillers(self):
        words = make_words("um", "uh", "like")
        result = find_fillers(words)
        assert result == [0, 1, 2]


class TestVocalizedFillerPattern:
    """Elongated disfluency spellings must be caught, real words must not."""

    @pytest.mark.parametrize("token", [
        "um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm", "uhmm",
        "ah", "ahh", "ahhh", "ahm", "er", "err", "erm", "eh", "ehh",
        "hm", "hmm", "hmmm", "mhm", "mm", "mmm",
    ])
    def test_vocalized_fillers_detected(self, token):
        assert is_filler(token)

    @pytest.mark.parametrize("token", [
        "a", "i", "the", "am", "him", "them", "me", "he", "her", "home",
        "area", "eyes", "mean", "more", "each", "hand", "arm", "ears", "hear",
    ])
    def test_real_words_not_flagged(self, token):
        assert not is_filler(token)

    def test_elongated_in_word_list(self):
        words = [{"word": "Ahhh,"}, {"word": "breathe"}, {"word": "uhh"}]
        assert find_fillers(words) == [0, 2]

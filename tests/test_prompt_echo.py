"""
Whisper will transcribe its own initial_prompt as if it were speech. Feeding it
a comma-separated vocabulary list once put 2,747 echoes into these recordings
and displaced ~51 minutes of real speech, so this is pinned in two places:
the hint must never reach initial_prompt, and any echo that still appears is
stripped from the output.
"""
import pytest
from core.transcriber import drop_prompt_echo, VERBATIM_PRIMER

PROMPT = ("Acme Robotics, ACR, HELIOS, QX-7, Priya, Marco, Lena, Tomasz, "
          "dataset, multimodal, work package, consortium, budget.")


def mk(text):
    return [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25}
            for i, w in enumerate(text.split())]


def text_of(words):
    return " ".join(w["word"] for w in words)


class TestDropPromptEcho:
    def test_removes_a_verbatim_echo(self):
        words = mk("we should conflate them") + mk(PROMPT) + mk("and in some cases")
        out = drop_prompt_echo(words, [None, PROMPT])
        assert "HELIOS" not in text_of(out)
        assert text_of(out) == "we should conflate them and in some cases"

    def test_removes_repeated_echoes(self):
        words = mk("okay") + mk(PROMPT) + mk(PROMPT) + mk("right")
        assert text_of(drop_prompt_echo(words, [None, PROMPT])) == "okay right"

    def test_keeps_a_real_mention_of_a_prompt_word(self):
        words = mk("the HELIOS dataset is the multimodal one")
        assert drop_prompt_echo(words, [None, PROMPT]) == words

    def test_keeps_several_prompt_words_in_natural_speech(self):
        # people do say these words; they just never recite the list in order
        words = mk("Priya and Marco discussed the budget for the consortium")
        assert drop_prompt_echo(words, [None, PROMPT]) == words

    def test_short_runs_survive(self):
        words = mk("Lena Tomasz dataset")          # 3 < min_run
        assert drop_prompt_echo(words, [None, PROMPT]) == words

    def test_out_of_order_sequence_is_not_an_echo(self):
        words = mk("budget consortium multimodal dataset Tomasz Lena Marco")
        assert drop_prompt_echo(words, [None, PROMPT]) == words

    def test_primer_echo_removed(self):
        words = mk("so anyway") + mk(VERBATIM_PRIMER)
        assert len(drop_prompt_echo(words, [VERBATIM_PRIMER, None])) < len(words)

    def test_no_prompt_means_no_change(self):
        words = mk("nothing to strip here at all")
        assert drop_prompt_echo(words, [None, None]) == words

    def test_empty(self):
        assert drop_prompt_echo([], [PROMPT]) == []

    def test_punctuation_and_case_insensitive(self):
        noisy = PROMPT.replace(",", "").upper()
        words = mk("hello") + mk(noisy) + mk("goodbye")
        assert text_of(drop_prompt_echo(words, [None, PROMPT])) == "hello goodbye"


class TestPromptConstruction:
    def test_vocabulary_never_reaches_initial_prompt(self, monkeypatch):
        """The hint must arrive as hotwords only — this is the actual bug."""
        import core.transcriber as tr
        seen = {}

        def fake_load(prompt, hotwords):
            seen["prompt"], seen["hotwords"] = prompt, hotwords
            raise RuntimeError("stop here — we only need the arguments")

        monkeypatch.setattr(tr, "_load_asr_model", fake_load)
        with pytest.raises(RuntimeError):
            tr.transcribe("/nonexistent.m4a", initial_prompt="HELIOS, QX-7, ACR")

        assert "HELIOS" in (seen["hotwords"] or "")
        assert "HELIOS" not in (seen["prompt"] or "")
        assert seen["prompt"] == tr.VERBATIM_PRIMER


class TestCollapseLoops:
    """Whisper gets stuck repeating a phrase on quiet audio; that is noise."""

    def test_stuck_loop_collapsed_to_two(self):
        from core.transcriber import collapse_loops
        words = mk("he said") + mk("Um, so, um, yeah. " * 8) + mk("and we moved on")
        out = text_of(collapse_loops(words))
        assert out.count("yeah.") == 2
        assert out.startswith("he said") and out.endswith("and we moved on")

    def test_single_word_loop(self):
        from core.transcriber import collapse_loops
        assert text_of(collapse_loops(mk("the the the the the cat"))) == "the the cat"

    def test_emphasis_survives(self):
        from core.transcriber import collapse_loops
        words = mk("look very, very closely")
        assert collapse_loops(words) == words

    def test_rhetorical_repetition_survives(self):
        from core.transcriber import collapse_loops
        words = mk("feeling more and more and more alive")
        assert collapse_loops(words) == words

    def test_empty(self):
        from core.transcriber import collapse_loops
        assert collapse_loops([]) == []

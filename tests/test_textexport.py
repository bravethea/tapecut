# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import pytest
from core import textexport


def mk(*rows):
    """rows: (word, start, end, speaker|None, deleted)"""
    return [{"word": w, "start": s, "end": e, "speaker": spk, "deleted": d}
            for w, s, e, spk, d in rows]


WORDS = mk(
    ("Hello", 0.0, 0.4, "SPEAKER_00", False),
    ("there.", 0.4, 0.9, "SPEAKER_00", False),
    ("Hi", 1.2, 1.4, "SPEAKER_01", False),
    ("um", 1.4, 1.6, "SPEAKER_01", True),
    ("back.", 1.6, 2.1, "SPEAKER_01", False),
)
NAMES = {"SPEAKER_00": "Teodora", "SPEAKER_01": "Sean"}


class TestText:
    def test_speaker_labels_used(self):
        out = textexport.to_text(WORDS, names=NAMES)
        assert "Teodora: Hello there." in out
        assert "Sean: Hi back." in out

    def test_cut_words_excluded_by_default(self):
        assert "um" not in textexport.to_text(WORDS, names=NAMES)

    def test_cut_words_bracketed_when_included(self):
        out = textexport.to_text(WORDS, names=NAMES, include_cut=True)
        assert "Hi [um] back." in out

    def test_raw_ids_when_unnamed(self):
        assert "SPEAKER_00:" in textexport.to_text(WORDS)

    def test_no_speakers_means_no_labels(self):
        plain = mk(("Just", 0.0, 0.3, None, False), ("words.", 0.3, 0.7, None, False))
        assert textexport.to_text(plain).strip() == "Just words."

    def test_empty(self):
        assert textexport.to_text([]) == ""


class TestMarkdown:
    def test_headings_and_speakers(self):
        out = textexport.to_markdown(WORDS, "Session", NAMES)
        assert out.startswith("# Session")
        assert "**Teodora**" in out and "**Sean**" in out

    def test_note_when_cut_words_included(self):
        assert "[brackets]" in textexport.to_markdown(WORDS, "S", NAMES, include_cut=True)


class TestCaptions:
    def test_srt_shape(self):
        out = textexport.to_srt(WORDS, NAMES)
        assert out.startswith("1\n")
        assert "00:00:00,000 --> 00:00:00,900" in out

    def test_vtt_header_and_dot_timestamps(self):
        out = textexport.to_vtt(WORDS, NAMES)
        assert out.startswith("WEBVTT")
        assert "00:00:00.000 -->" in out

    def test_cue_breaks_on_speaker_change(self):
        # two speakers → at least two cues
        assert textexport.to_srt(WORDS, NAMES).count(" --> ") == 2


class TestRender:
    @pytest.mark.parametrize("fmt", sorted(textexport.FORMATS))
    def test_every_format_produces_text(self, fmt):
        assert textexport.render(fmt, WORDS, "T", NAMES).strip()

    def test_unknown_format_rejected(self):
        with pytest.raises(ValueError):
            textexport.render("docx", WORDS)

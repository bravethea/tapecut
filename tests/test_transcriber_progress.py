# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
A long transcription used to show nothing but a clock for half an hour.
transcribe() now forwards whisperX's per-chunk progress, scaled so recognition
fills 0–0.9 and alignment the rest, and uses more than whisperX's default 4
CPU threads.
"""
import pytest

import core.transcriber as tr


class _Stop(Exception):
    pass


def _fake_model(percents):
    class Model:
        def transcribe(self, audio, progress_callback=None, **kw):
            for p in percents:
                if progress_callback:
                    progress_callback(p)
            raise _Stop        # recognition is all this test needs
    return Model()


def _run(monkeypatch, percents, progress):
    import whisperx
    monkeypatch.setattr(tr, "_load_asr_model", lambda *a: _fake_model(percents))
    monkeypatch.setattr(whisperx, "load_audio", lambda path: b"")
    with pytest.raises(_Stop):
        tr.transcribe("/nonexistent.m4a", progress=progress)


def test_progress_is_scaled_into_the_first_nine_tenths(monkeypatch):
    seen = []
    _run(monkeypatch, [25, 50, 100], seen.append)
    assert seen == pytest.approx([0.225, 0.45, 0.9])


def test_no_progress_callback_is_fine(monkeypatch):
    _run(monkeypatch, [50], None)


def test_uses_at_least_whisperx_default_threads():
    assert tr.CPU_THREADS >= 4

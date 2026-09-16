# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Structural test for transcriber output. Does NOT test accuracy.
Requires: mlx-whisper installed and tests/fixtures/sample_5s.wav present.
Skip automatically if either is missing.
"""
import pytest


@pytest.fixture(scope="module")
def sample_audio(tmp_path_factory):
    """Use the bundled fixture if present, else skip."""
    import importlib.util
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "sample_5s.wav"
    if not fixture.exists():
        pytest.skip("No sample audio fixture found at tests/fixtures/sample_5s.wav")
    if importlib.util.find_spec("mlx_whisper") is None:
        pytest.skip("mlx-whisper not installed")
    return str(fixture)


def test_transcriber_output_structure(sample_audio):
    from core.transcriber import transcribe

    words = transcribe(sample_audio)

    assert isinstance(words, list), "transcribe() must return a list"
    assert len(words) > 0, "word list must not be empty for a 5s clip with speech"

    for i, w in enumerate(words):
        assert "word" in w, f"word[{i}] missing 'word' key"
        assert "start" in w, f"word[{i}] missing 'start' key"
        assert "end" in w, f"word[{i}] missing 'end' key"
        assert "probability" in w, f"word[{i}] missing 'probability' key"
        assert isinstance(w["word"], str), f"word[{i}]['word'] must be str"
        assert isinstance(w["start"], float), f"word[{i}]['start'] must be float"
        assert isinstance(w["end"], float), f"word[{i}]['end'] must be float"
        assert 0.0 <= w["probability"] <= 1.0, f"probability out of range at word[{i}]"
        assert w["start"] >= 0.0, f"negative start time at word[{i}]"
        assert w["end"] >= w["start"], f"end < start at word[{i}]"

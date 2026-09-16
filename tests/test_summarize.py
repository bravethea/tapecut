# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import pytest
from core import summarize

TRANSCRIPT = """Teodora: Let us start. We decided to move the release to next week.
Sean: I will send the draft by Friday. Can you review the metrics?
Teodora: Yes, I need to update the dashboard. What about the budget?
Sean: The plan is to keep it flat. Let us follow up next month."""


class TestLocalBackend:
    def test_todos_are_extracted_as_checklist(self):
        out = summarize.analyse("todos", TRANSCRIPT, backend="local")
        assert out["backend"] == "local"
        assert "- [ ]" in out["text"]
        assert "draft by Friday" in out["text"]

    def test_meeting_notes_have_sections(self):
        text = summarize.analyse("meeting", TRANSCRIPT, backend="local")["text"]
        assert "## Decisions" in text and "## Action items" in text
        assert "move the release" in text

    def test_questions_surface(self):
        text = summarize.analyse("meeting", TRANSCRIPT, backend="local")["text"]
        assert "budget" in text

    def test_summary_lists_topics(self):
        text = summarize.analyse("summary", TRANSCRIPT, backend="local")["text"]
        assert "## Most discussed" in text

    def test_local_output_says_it_is_extraction(self):
        text = summarize.analyse("todos", TRANSCRIPT, backend="local")["text"]
        assert "built-in" in text.lower()

    def test_no_actions_is_stated_plainly(self):
        text = summarize.analyse("todos", "Teodora: The sky is blue today.",
                                 backend="local")["text"]
        assert text.startswith("No action items found.")


class TestGuards:
    def test_unknown_kind(self):
        with pytest.raises(summarize.SummarizeError):
            summarize.analyse("horoscope", TRANSCRIPT)

    def test_empty_transcript(self):
        with pytest.raises(summarize.SummarizeError):
            summarize.analyse("summary", "   ")

    def test_backend_info_shape(self):
        info = summarize.backend_info()
        assert info["backend"] in {"api", "cli", "local"}
        assert info["label"]

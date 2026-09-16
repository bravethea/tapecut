# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
Main application window. Wires together the toolbar, transcript view,
initial-prompt panel, and status bar. All cross-module signal connections live here.

Flow: Open media (audio or video) → Transcribe (or auto-load saved project)
      → click/drag words to cut → Play Preview → Export (audio or video).
"""
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QFileDialog, QStatusBar, QMessageBox, QLabel,
    QTextEdit, QGroupBox, QComboBox, QPushButton, QFrame,
    QProgressDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QShortcut

from core.transcriber import TranscriberThread, is_model_cached, SUPPORTED_FORMATS
from core.audio_editor import (
    compute_kept_segments, build_edited_audio, kept_indices_from_words,
    build_edited_timeline, word_index_at_edited_time,
)
from core.player import AudioPlayer
from core.export import (
    export_audio, export_video_via_ffmpeg, is_video_file,
)
from core.filler_detector import find_fillers
from core import project
from ui.transcript_view import TranscriptView

LANGUAGES = [
    ("English", "en"), ("German", "de"), ("French", "fr"), ("Spanish", "es"),
    ("Italian", "it"), ("Serbian", "sr"), ("Croatian", "hr"), ("Dutch", "nl"),
    ("Auto-detect", ""),
]


class _PreviewBuilder(QThread):
    """Builds the edited AudioSegment off the main thread (pydub decode is slow)."""
    done = pyqtSignal(object)   # AudioSegment
    error = pyqtSignal(str)

    def __init__(self, source_path: str, segments: list[tuple[float, float]]):
        super().__init__()
        self._source = source_path
        self._segments = segments

    def run(self):
        try:
            self.done.emit(build_edited_audio(self._source, self._segments))
        except Exception as exc:
            self.error.emit(str(exc))


class _Exporter(QThread):
    done = pyqtSignal(str)      # output path
    error = pyqtSignal(str)

    def __init__(self, source_path: str, segments, output_path: str):
        super().__init__()
        self._source = source_path
        self._segments = segments
        self._output = output_path

    def run(self):
        try:
            if Path(self._output).suffix.lower() in {".mp3", ".wav"}:
                segment = build_edited_audio(self._source, self._segments)
                if segment is None:
                    raise ValueError("Nothing to export — all words are deleted.")
                export_audio(segment, self._output)
            else:
                export_video_via_ffmpeg(self._source, self._segments, self._output)
            self.done.emit(self._output)
        except Exception as exc:
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Tapecut")
        self.resize(1000, 750)

        self._media_path: str | None = None
        self._transcriber: TranscriberThread | None = None
        self._preview_builder: _PreviewBuilder | None = None
        self._exporter: _Exporter | None = None
        self._player = AudioPlayer(self)
        self._timeline: list = []           # (edited_start, edited_end, word_idx)
        self._preview_dirty = True
        self._paused_at: float = 0.0
        self._pending_play_from: float | None = None
        self._transcribe_t0: float = 0.0
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._act_open = QAction("Open…", self)
        self._act_open.setShortcut(QKeySequence.StandardKey.Open)
        toolbar.addAction(self._act_open)

        self._act_transcribe = QAction("Transcribe", self)
        self._act_transcribe.setEnabled(False)
        toolbar.addAction(self._act_transcribe)

        toolbar.addSeparator()

        self._act_play = QAction("▶ Preview", self)
        self._act_play.setEnabled(False)
        toolbar.addAction(self._act_play)

        self._act_stop = QAction("■ Stop", self)
        self._act_stop.setEnabled(False)
        toolbar.addAction(self._act_stop)

        toolbar.addSeparator()

        self._act_fillers = QAction("Find Fillers", self)
        self._act_fillers.setEnabled(False)
        toolbar.addAction(self._act_fillers)

        self._act_undo = QAction("Undo", self)
        self._act_undo.setEnabled(False)
        toolbar.addAction(self._act_undo)

        toolbar.addSeparator()

        self._act_export = QAction("Export…", self)
        self._act_export.setEnabled(False)
        self._act_export.setShortcut("Ctrl+E")
        toolbar.addAction(self._act_export)

        # language selector lives at the right end of the toolbar
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addWidget(QLabel("Language: "))
        self._lang_combo = QComboBox()
        for name, code in LANGUAGES:
            self._lang_combo.addItem(name, code)
        toolbar.addWidget(self._lang_combo)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Initial prompt panel (collapsible)
        self._prompt_group = QGroupBox("Vocabulary hint (names, terms, spellings — improves transcription)")
        self._prompt_group.setCheckable(True)
        self._prompt_group.setChecked(True)
        prompt_layout = QVBoxLayout(self._prompt_group)
        self._prompt_input = QTextEdit()
        self._prompt_input.setPlaceholderText(
            "e.g. Vipassana, samadhi, metta, jhāna, Ajahn Chah…"
        )
        self._prompt_input.setMaximumHeight(60)
        prompt_layout.addWidget(self._prompt_input)
        self._prompt_group.toggled.connect(
            lambda on: self._prompt_input.setVisible(on)
        )
        layout.addWidget(self._prompt_group)

        # Filler review bar (hidden until Find Fillers)
        self._filler_bar = QFrame()
        self._filler_bar.setStyleSheet(
            "QFrame { background: #fff3e0; border: 1px solid #ffb74d; border-radius: 4px; }"
        )
        fb_layout = QHBoxLayout(self._filler_bar)
        self._filler_label = QLabel()
        self._filler_label.setWordWrap(True)  # long filler lists must not widen the window
        fb_layout.addWidget(self._filler_label, stretch=1)
        self._btn_filler_apply = QPushButton("Delete them")
        self._btn_filler_cancel = QPushButton("Cancel")
        fb_layout.addWidget(self._btn_filler_apply)
        fb_layout.addWidget(self._btn_filler_cancel)
        self._filler_bar.hide()
        layout.addWidget(self._filler_bar)

        # Transcript
        self._transcript = TranscriptView()
        self._transcript.setPlaceholderText(
            "Open an audio or video file (⌘O), then click Transcribe.\n\n"
            "Click a word to cut it · drag to cut a range · ⌥-click to restore · "
            "right-click to play from a word · Space to play/pause."
        )
        layout.addWidget(self._transcript, stretch=1)

        # Status bar: message (left) + duration stats (right)
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._stats_label = QLabel("")
        self._status.addPermanentWidget(self._stats_label)
        self._status.showMessage("Ready")

        # Cmd+Z scoped to the transcript so the prompt box keeps its own undo
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self._transcript)
        self._undo_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

        self._act_save = QAction("Save project", self)
        self._act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.addAction(self._act_save)

        # AGPL "Appropriate Legal Notices" for the desktop UI. macOS moves an
        # action with the AboutRole into the application menu automatically.
        self._act_about = QAction("About Tapecut", self)
        self._act_about.setMenuRole(QAction.MenuRole.AboutRole)
        self.menuBar().addMenu("Help").addAction(self._act_about)

    def _wire_signals(self) -> None:
        self._act_about.triggered.connect(self._on_about)
        self._act_open.triggered.connect(self._on_open)
        self._act_transcribe.triggered.connect(self._on_transcribe)
        self._act_play.triggered.connect(self._on_play_pause)
        self._act_stop.triggered.connect(self._on_stop)
        self._act_export.triggered.connect(self._on_export)
        self._act_fillers.triggered.connect(self._on_find_fillers)
        self._act_undo.triggered.connect(self._transcript.undo)
        self._act_save.triggered.connect(self._save_project)
        self._undo_shortcut.activated.connect(self._transcript.undo)

        self._btn_filler_apply.clicked.connect(self._on_filler_apply)
        self._btn_filler_cancel.clicked.connect(self._on_filler_cancel)

        self._transcript.words_edited.connect(self._on_words_edited)
        self._transcript.play_from_word.connect(self._on_play_from_word)
        self._transcript.play_pause.connect(self._on_play_pause)

        self._player.position_changed.connect(self._on_position)
        self._player.playback_finished.connect(self._on_playback_finished)

    # ------------------------------------------------------------------ open

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Tapecut",
            "<b>Tapecut</b><br>Edit audio and video by editing the transcript."
            "<p>Copyright \u00a9 2025\u20132026 Teodora Vukovi\u0107 "
            "(Teodora Vukovic).</p>"
            "<p>Free software under the "
            '<a href="https://www.gnu.org/licenses/agpl-3.0.html">GNU Affero '
            "General Public License v3</a> or later. This program comes with "
            "ABSOLUTELY NO WARRANTY.</p>",
        )

    def _on_open(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(SUPPORTED_FORMATS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Audio or Video File", "",
            f"Media Files ({exts});;All Files (*)"
        )
        if not path:
            return

        self._on_stop()
        self._media_path = path
        self._preview_dirty = True
        self._act_transcribe.setEnabled(True)
        kind = "video" if is_video_file(path) else "audio"
        self.setWindowTitle(f"Tapecut — {Path(path).name}")

        if project.has_project(path):
            try:
                data = project.load_project(path)
                self._prompt_input.setPlainText(data["prompt"])
                self._load_words(data["words"])
                self._status.showMessage(
                    f"Loaded {kind} + saved transcript ({len(data['words'])} words). "
                    "Edit away — no need to re-transcribe."
                )
                return
            except Exception:
                pass  # corrupt sidecar — fall through to fresh state

        self._transcript.load_words([])
        self._set_edit_actions_enabled(False)
        self._status.showMessage(f"Loaded {kind}: {Path(path).name} — now click Transcribe")

    # ------------------------------------------------------------ transcribe

    def _on_transcribe(self) -> None:
        if not self._media_path:
            return
        if self._transcriber and self._transcriber.isRunning():
            return

        if not is_model_cached():
            reply = QMessageBox.question(
                self, "Model download required",
                "The Whisper model (~1.6 GB) is not downloaded yet.\n"
                "The first transcription will download it — this needs internet "
                "and can take a few minutes.\n\nContinue?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        prompt = self._prompt_input.toPlainText().strip() or None
        language = self._lang_combo.currentData() or None

        self._transcriber = TranscriberThread(self._media_path, prompt, language)
        self._transcriber.done.connect(self._on_transcribed)
        self._transcriber.error.connect(self._on_transcribe_error)

        self._act_transcribe.setEnabled(False)
        self._act_open.setEnabled(False)
        self._transcribe_t0 = time.time()
        self._elapsed_timer.start(1000)
        self._status.showMessage("Transcribing… 0s")
        self._transcriber.start()

    def _tick_elapsed(self) -> None:
        self._status.showMessage(f"Transcribing… {int(time.time() - self._transcribe_t0)}s")

    def _on_transcribed(self, words: list) -> None:
        self._elapsed_timer.stop()
        self._act_open.setEnabled(True)
        self._act_transcribe.setEnabled(True)
        took = int(time.time() - self._transcribe_t0)

        if not words:
            QMessageBox.warning(
                self, "Empty transcript",
                "Transcription returned no words. Is the file silent, or in "
                "another language? Try the language dropdown or Auto-detect."
            )
            self._status.showMessage("Transcription returned no words")
            return

        self._load_words(words)
        self._prompt_group.setChecked(False)   # collapse prompt panel
        self._save_project()
        self._status.showMessage(
            f"Transcribed {len(words)} words in {took}s — project auto-saved. "
            "Click words to cut them."
        )

    def _on_transcribe_error(self, message: str) -> None:
        self._elapsed_timer.stop()
        self._act_open.setEnabled(True)
        self._act_transcribe.setEnabled(True)
        self._status.showMessage("Transcription failed")
        QMessageBox.critical(
            self, "Transcription failed",
            f"{message}\n\nIf this is a codec problem, try converting first:\n"
            f"ffmpeg -i \"{self._media_path}\" -ar 16000 out.wav"
        )

    def _load_words(self, words: list) -> None:
        self._transcript.load_words(words)
        self._transcript.setFocus()
        self._set_edit_actions_enabled(True)
        self._preview_dirty = True
        self._update_stats()

    def _set_edit_actions_enabled(self, on: bool) -> None:
        for act in (self._act_play, self._act_stop, self._act_export,
                    self._act_fillers, self._act_undo):
            act.setEnabled(on)

    # ------------------------------------------------------------ edits/stats

    def _on_words_edited(self) -> None:
        self._preview_dirty = True
        if self._player.is_playing():
            self._on_stop()
        self._update_stats()
        self._save_project()

    def _update_stats(self) -> None:
        words = self._transcript.words
        if not words:
            self._stats_label.setText("")
            return
        total = words[-1]["end"] - words[0]["start"]
        kept = kept_indices_from_words(words)
        segments = compute_kept_segments(words, kept)
        kept_dur = sum(e - s for s, e in segments)
        cut = len(words) - len(kept)

        def fmt(sec: float) -> str:
            m, s = divmod(int(sec), 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

        self._stats_label.setText(
            f"{cut} words cut  ·  kept {fmt(kept_dur)} of {fmt(total)}  "
        )

    def _save_project(self) -> None:
        if self._media_path and self._transcript.words:
            try:
                project.save_project(
                    self._media_path, self._transcript.words,
                    self._prompt_input.toPlainText(),
                )
            except Exception as exc:
                self._status.showMessage(f"Warning: could not save project ({exc})")

    # ------------------------------------------------------------ playback

    def _on_play_pause(self) -> None:
        if not self._transcript.words:
            return
        if self._player.is_playing():
            self._paused_at = self._player.current_time()
            self._player.pause()
            self._act_play.setText("▶ Preview")
            self._status.showMessage("Paused")
            return

        if self._preview_dirty:
            self._start_preview_build(play_from=self._paused_at if not self._pending_play_from else None)
        else:
            self._player.play(from_sec=self._paused_at)
            self._act_play.setText("⏸ Pause")
            self._status.showMessage("Playing preview (deleted parts skipped)")

    def _on_play_from_word(self, word_idx: int) -> None:
        # find the edited-time position of this word (or the next kept one)
        if self._preview_dirty:
            self._pending_play_from = float(word_idx)  # resolve after build
            self._start_preview_build()
            return
        t = self._edited_time_for_word(word_idx)
        if t is None:
            self._status.showMessage("That word is deleted — nothing to play there")
            return
        self._paused_at = t
        self._player.play(from_sec=t)
        self._act_play.setText("⏸ Pause")

    def _edited_time_for_word(self, word_idx: int) -> float | None:
        for ed_start, _ed_end, idx in self._timeline:
            if idx >= word_idx:
                return ed_start
        return None

    def _start_preview_build(self, play_from: float | None = None) -> None:
        if self._preview_builder and self._preview_builder.isRunning():
            return
        words = self._transcript.words
        kept = kept_indices_from_words(words)
        if not kept:
            self._status.showMessage("Everything is deleted — nothing to play")
            return
        segments = compute_kept_segments(words, kept)
        self._timeline = build_edited_timeline(words, kept)
        if play_from is not None:
            self._paused_at = play_from

        self._status.showMessage("Building preview…")
        self._act_play.setEnabled(False)
        self._preview_builder = _PreviewBuilder(self._media_path, segments)
        self._preview_builder.done.connect(self._on_preview_ready)
        self._preview_builder.error.connect(self._on_preview_error)
        self._preview_builder.start()

    def _on_preview_ready(self, segment) -> None:
        self._act_play.setEnabled(True)
        if segment is None:
            return
        self._player.load_segment(segment)
        self._preview_dirty = False

        start = 0.0
        if self._pending_play_from is not None:
            t = self._edited_time_for_word(int(self._pending_play_from))
            start = t if t is not None else 0.0
            self._pending_play_from = None
        elif self._paused_at:
            start = self._paused_at

        self._paused_at = start
        self._player.play(from_sec=start)
        self._act_play.setText("⏸ Pause")
        self._status.showMessage("Playing preview (deleted parts skipped)")

    def _on_preview_error(self, message: str) -> None:
        self._act_play.setEnabled(True)
        self._pending_play_from = None
        QMessageBox.critical(self, "Preview failed", message)

    def _on_stop(self) -> None:
        self._player.stop()
        self._paused_at = 0.0
        self._act_play.setText("▶ Preview")
        self._transcript.clear_playing()

    def _on_position(self, sec: float) -> None:
        idx = word_index_at_edited_time(self._timeline, sec)
        if idx >= 0:
            self._transcript.mark_playing(idx)

    def _on_playback_finished(self) -> None:
        self._paused_at = 0.0
        self._act_play.setText("▶ Preview")
        self._transcript.clear_playing()

    # ------------------------------------------------------------ fillers

    def _on_find_fillers(self) -> None:
        indices = find_fillers(self._transcript.words)
        if not indices:
            self._status.showMessage("No filler words found")
            return
        self._transcript.set_filler_flags(indices)
        self._filler_indices = indices
        self._filler_label.setText(
            f"Found {len(indices)} filler words (orange underline). "
            "⌥-click any to keep it, then:"
        )
        self._filler_bar.show()

    def _on_filler_apply(self) -> None:
        # only delete the ones still flagged (user may have restored some)
        to_delete = [i for i in self._filler_indices
                     if self._transcript.words[i].get("filler")]
        self._transcript.clear_filler_flags()
        self._filler_bar.hide()
        self._transcript.set_deleted(to_delete, True)
        self._status.showMessage(f"Deleted {len(to_delete)} filler words")

    def _on_filler_cancel(self) -> None:
        self._transcript.clear_filler_flags()
        self._filler_bar.hide()

    # ------------------------------------------------------------ export

    def _on_export(self) -> None:
        words = self._transcript.words
        if not words or not self._media_path:
            return
        kept = kept_indices_from_words(words)
        if not kept:
            QMessageBox.warning(self, "Nothing to export", "All words are deleted.")
            return

        src = Path(self._media_path)
        if is_video_file(self._media_path):
            default = str(src.with_name(f"{src.stem}_edited.mp4"))
            filters = "Video — MP4, YouTube-ready (*.mp4);;Audio only — MP3 (*.mp3);;Audio only — WAV (*.wav)"
        else:
            default = str(src.with_name(f"{src.stem}_edited.mp3"))
            filters = "MP3 (*.mp3);;WAV (*.wav)"

        out, _ = QFileDialog.getSaveFileName(self, "Export edited file", default, filters)
        if not out:
            return

        segments = compute_kept_segments(words, kept)
        self._export_progress = QProgressDialog("Exporting…", None, 0, 0, self)
        self._export_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._export_progress.setMinimumDuration(0)
        self._export_progress.setCancelButton(None)
        self._export_progress.show()

        self._exporter = _Exporter(self._media_path, segments, out)
        self._exporter.done.connect(self._on_export_done)
        self._exporter.error.connect(self._on_export_error)
        self._exporter.start()

    def _on_export_done(self, output_path: str) -> None:
        self._export_progress.close()
        self._save_project()
        self._status.showMessage(f"Exported: {output_path}")
        QMessageBox.information(
            self, "Export complete",
            f"Saved:\n{output_path}\n\nDeleted sections are removed."
        )

    def _on_export_error(self, message: str) -> None:
        self._export_progress.close()
        QMessageBox.critical(self, "Export failed", message)

    # ------------------------------------------------------------ close

    def closeEvent(self, event) -> None:
        self._save_project()
        self._player.stop()
        event.accept()

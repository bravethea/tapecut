# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
TranscriptView — word-level editable transcript widget.

Architecture:
  - QTextEdit in read-only mode as the base widget
  - Words rendered as a flat character stream; per-word char ranges tracked in self._ranges
  - Mouse events map click position → char offset → word index via binary search
  - Per-word QTextCharFormat applied via a QTextCursor

Interaction model:
  - Click a word            → toggle deleted
  - Drag across words       → mark the whole range deleted
  - Alt+drag / Alt+click    → restore (undelete) range
  - Right-click             → context menu (Play from here, Restore, Delete to end)
  - Space                   → play/pause (emitted to MainWindow)
  - Cmd+Z                   → undo last edit

Word visual states:
  - normal:   default text
  - deleted:  red background, strikethrough
  - playing:  yellow background
  - filler:   orange underline (pending review)
"""
from PyQt6.QtWidgets import QTextEdit, QMenu
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import (
    QTextCharFormat, QColor, QFont, QTextCursor,
    QMouseEvent, QKeyEvent, QTextOption,
)

MAX_UNDO = 200


class TranscriptView(QTextEdit):
    words_edited = pyqtSignal()        # any change to deleted flags
    play_from_word = pyqtSignal(int)   # right-click "Play from here" (word index)
    play_pause = pyqtSignal()          # space bar

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        font = QFont()
        font.setPointSize(15)
        self.setFont(font)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)

        self._words: list[dict] = []
        self._ranges: list[tuple[int, int]] = []  # (char_start, char_end) per word
        self._playing_index: int = -1
        self._drag_start: int = -1
        self._drag_moved: bool = False
        self._drag_restore: bool = False           # Alt held → restore instead of delete
        self._drag_last_range: tuple[int, int] | None = None
        self._undo_stack: list[list[bool]] = []

    # ---------------------------------------------------------------- loading

    def load_words(self, words: list[dict]) -> None:
        """Render a word list into the text edit and rebuild char range map."""
        self._words = words
        self._ranges = []
        self._playing_index = -1
        self._undo_stack.clear()
        self.clear()

        cursor = self.textCursor()
        pos = 0
        for w in words:
            text = w["word"] + " "
            self._ranges.append((pos, pos + len(w["word"])))
            cursor.insertText(text)
            pos += len(text)

        self._refresh_all_formats()

    @property
    def words(self) -> list[dict]:
        return self._words

    # ---------------------------------------------------------------- editing

    def set_deleted(self, indices, deleted: bool = True, push_undo: bool = True) -> None:
        """Programmatic edit (used for filler removal etc.)."""
        if push_undo:
            self._push_undo()
        for i in indices:
            self._words[i]["deleted"] = deleted
        self._refresh_all_formats()
        self.words_edited.emit()

    def set_filler_flags(self, indices) -> None:
        marked = set(indices)
        for i, w in enumerate(self._words):
            w["filler"] = i in marked
        self._refresh_all_formats()

    def clear_filler_flags(self) -> None:
        for w in self._words:
            w.pop("filler", None)
        self._refresh_all_formats()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        flags = self._undo_stack.pop()
        for w, flag in zip(self._words, flags):
            w["deleted"] = flag
        self._refresh_all_formats()
        self.words_edited.emit()

    def _push_undo(self) -> None:
        self._undo_stack.append([bool(w.get("deleted")) for w in self._words])
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)

    # ---------------------------------------------------------------- playhead

    def mark_playing(self, word_index: int) -> None:
        """Highlight the currently playing word (O(1) — only repaints 2 words)."""
        if word_index == self._playing_index:
            return
        prev = self._playing_index
        self._playing_index = word_index
        if 0 <= prev < len(self._words):
            self._apply_format(prev)
        if 0 <= word_index < len(self._words):
            self._apply_format(word_index)
            self._scroll_to_word(word_index)

    def clear_playing(self) -> None:
        self.mark_playing(-1)

    def _scroll_to_word(self, idx: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._ranges[idx][0])
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    # ---------------------------------------------------------------- painting

    def _apply_format(self, i: int) -> None:
        w = self._words[i]
        start, end = self._ranges[i]
        fmt = QTextCharFormat()

        if i == self._playing_index and not w.get("deleted"):
            fmt.setBackground(QColor("#fff176"))
        elif w.get("deleted"):
            fmt.setBackground(QColor("#ffcccc"))
            fmt.setForeground(QColor("#b71c1c"))
            fmt.setFontStrikeOut(True)
        elif w.get("filler"):
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            fmt.setUnderlineColor(QColor("#ff9800"))

        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(fmt)

    def _refresh_all_formats(self) -> None:
        for i in range(len(self._words)):
            self._apply_format(i)

    # ---------------------------------------------------------------- helpers

    def _word_index_at(self, pos: int) -> int:
        """Binary search: char offset → word index (nearest word, -1 if empty)."""
        if not self._ranges:
            return -1
        lo, hi = 0, len(self._ranges) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            start, end = self._ranges[mid]
            if pos < start:
                hi = mid - 1
            elif pos > end:
                lo = mid + 1
            else:
                return mid
        # between words (on trailing space) — snap to previous word
        return max(0, min(hi, len(self._ranges) - 1))

    def _index_from_event(self, e) -> int:
        pos = self.cursorForPosition(e.position().toPoint()).position()
        return self._word_index_at(pos)

    # ---------------------------------------------------------------- events

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._words:
            self._drag_start = self._index_from_event(e)
            self._drag_moved = False
            self._drag_restore = bool(e.modifiers() & Qt.KeyboardModifier.AltModifier)
            self._drag_last_range = None
            e.accept()
            return  # suppress native text-selection
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag_start >= 0 and e.buttons() & Qt.MouseButton.LeftButton:
            idx = self._index_from_event(e)
            if idx >= 0 and idx != self._drag_start:
                if not self._drag_moved:
                    self._drag_moved = True
                    self._push_undo()
                lo, hi = sorted([self._drag_start, idx])
                # un-mark words that left the drag range
                if self._drag_last_range:
                    plo, phi = self._drag_last_range
                    for i in range(plo, phi + 1):
                        if i < lo or i > hi:
                            self._words[i]["deleted"] = self._drag_restore
                            self._apply_format(i)
                for i in range(lo, hi + 1):
                    self._words[i]["deleted"] = not self._drag_restore
                    self._apply_format(i)
                self._drag_last_range = (lo, hi)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton and self._drag_start >= 0:
            if self._drag_moved:
                self.words_edited.emit()
            else:
                idx = self._drag_start
                if 0 <= idx < len(self._words):
                    self._push_undo()
                    if self._drag_restore:
                        self._words[idx]["deleted"] = False
                    else:
                        self._words[idx]["deleted"] = not self._words[idx].get("deleted", False)
                    self._apply_format(idx)
                    self.words_edited.emit()
            self._drag_start = -1
            self._drag_moved = False
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e) -> None:
        if not self._words:
            return
        idx = self._word_index_at(self.cursorForPosition(e.pos()).position())
        if idx < 0:
            return
        menu = QMenu(self)
        act_play = menu.addAction("▶ Play from here")
        menu.addSeparator()
        act_del_to_end = menu.addAction("Delete from here to end")
        act_restore_all = menu.addAction("Restore everything")
        chosen = menu.exec(e.globalPos())
        if chosen == act_play:
            self.play_from_word.emit(idx)
        elif chosen == act_del_to_end:
            self.set_deleted(range(idx, len(self._words)), True)
        elif chosen == act_restore_all:
            self.set_deleted(range(len(self._words)), False)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Space:
            self.play_pause.emit()
            e.accept()
            return
        super().keyPressEvent(e)

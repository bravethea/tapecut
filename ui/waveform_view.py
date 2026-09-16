# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
"""
WaveformView — optional waveform display synced to playback position.
Implemented in Phase 8 (polish). Stub only.
"""
from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt
import numpy as np


class WaveformView(QWidget):
    """Displays a downsampled waveform; playhead follows AudioPlayer.position_changed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._samples: np.ndarray | None = None
        self._duration_sec: float = 0.0
        self._playhead_sec: float = 0.0

    def load_samples(self, samples: np.ndarray, samplerate: int) -> None:
        self._samples = samples
        self._duration_sec = len(samples) / samplerate
        self.update()

    def set_playhead(self, sec: float) -> None:
        self._playhead_sec = sec
        self.update()

    def paintEvent(self, event) -> None:
        if self._samples is None:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        w, h = self.width(), self.height()
        mid = h // 2
        painter.setPen(QColor("#4fc3f7"))

        # Downsample to one value per pixel
        n = len(self._samples)
        step = max(1, n // w)
        for x in range(w):
            chunk = self._samples[x * step: (x + 1) * step]
            if len(chunk) == 0:
                continue
            peak = float(np.abs(chunk).max())
            bar = int(peak * mid)
            painter.drawLine(x, mid - bar, x, mid + bar)

        # Playhead
        if self._duration_sec > 0:
            px = int(self._playhead_sec / self._duration_sec * w)
            painter.setPen(QColor("red"))
            painter.drawLine(px, 0, px, h)

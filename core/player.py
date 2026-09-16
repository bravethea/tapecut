# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
import threading
import numpy as np
import sounddevice as sd
from pydub import AudioSegment
from PyQt6.QtCore import QObject, pyqtSignal


class AudioPlayer(QObject):
    """
    Playback controller for original or edited audio.
    Emits position_changed(float) at ~30 fps with current playback time in seconds.
    All public methods are safe to call from the main thread.
    """

    position_changed = pyqtSignal(float)
    playback_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream: sd.OutputStream | None = None
        self._audio_data: np.ndarray | None = None
        self._samplerate: int = 44100
        self._frame_pos: int = 0
        self._playing: bool = False
        self._lock = threading.Lock()
        self._ticker: threading.Timer | None = None
        self._user_stopped: bool = False  # suppress playback_finished on pause/stop

    # ------------------------------------------------------------------ public

    def load_segment(self, segment: AudioSegment) -> None:
        """Load a pydub AudioSegment for playback."""
        self.stop()
        self._samplerate = segment.frame_rate
        samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
        if segment.channels == 2:
            samples = samples.reshape(-1, 2)
        else:
            samples = samples.reshape(-1, 1)
        samples /= float(2 ** (8 * segment.sample_width - 1))
        self._audio_data = samples
        self._frame_pos = 0

    def load_file(self, path: str) -> None:
        """Load an audio file directly."""
        self.load_segment(AudioSegment.from_file(path))

    def play(self, from_sec: float = 0.0) -> None:
        self.stop()
        if self._audio_data is None:
            return
        self._frame_pos = int(from_sec * self._samplerate)
        self._user_stopped = False
        self._playing = True
        self._stream = sd.OutputStream(
            samplerate=self._samplerate,
            channels=self._audio_data.shape[1] if self._audio_data.ndim > 1 else 1,
            dtype="float32",
            callback=self._callback,
            finished_callback=self._on_stream_finished,
        )
        self._stream.start()
        self._schedule_tick()

    def pause(self) -> None:
        if self._stream and self._playing:
            self._user_stopped = True
            self._playing = False
            self._stream.stop()
            self._cancel_tick()

    def stop(self) -> None:
        self._user_stopped = True
        self._playing = False
        self._cancel_tick()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._frame_pos = 0

    def is_playing(self) -> bool:
        return self._playing

    def current_time(self) -> float:
        return self._frame_pos / self._samplerate if self._samplerate else 0.0

    # ------------------------------------------------------------------ private

    def _callback(self, outdata: np.ndarray, frames: int, time, status) -> None:
        with self._lock:
            if self._audio_data is None or self._frame_pos >= len(self._audio_data):
                outdata[:] = 0
                raise sd.CallbackStop  # end of audio — stops stream, fires finished_callback
            end = min(self._frame_pos + frames, len(self._audio_data))
            chunk = self._audio_data[self._frame_pos:end]
            outdata[:len(chunk)] = chunk
            if len(chunk) < frames:
                outdata[len(chunk):] = 0
            self._frame_pos += frames

    def _on_stream_finished(self) -> None:
        self._playing = False
        self._cancel_tick()
        if not self._user_stopped:
            self.playback_finished.emit()

    def _schedule_tick(self) -> None:
        if not self._playing:
            return
        self.position_changed.emit(self.current_time())
        self._ticker = threading.Timer(1 / 30, self._schedule_tick)
        self._ticker.daemon = True
        self._ticker.start()

    def _cancel_tick(self) -> None:
        if self._ticker:
            self._ticker.cancel()
            self._ticker = None

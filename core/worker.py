"""
Qt Worker thread for running render jobs without blocking the UI.
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker, QWaitCondition
from core.video_processor import FilePair, RenderConfig, render_pair, build_pairs


class RenderWorker(QThread):
    # Signals
    progress = pyqtSignal(float, str)       # percent, message
    log_line = pyqtSignal(str)              # raw ffmpeg log line
    pair_done = pyqtSignal(str, str)        # index, output_path
    pair_error = pyqtSignal(str, str)       # index, error_message
    all_done = pyqtSignal(int, int)         # success_count, error_count
    stopped = pyqtSignal()
    paused = pyqtSignal()
    resumed = pyqtSignal()

    def __init__(self, pairs: list[FilePair], config: RenderConfig, parent=None):
        super().__init__(parent)
        self.pairs = pairs
        self.config = config
        self._abort = False
        self._paused = False
        self._pause_mutex = QMutex()
        self._pause_condition = QWaitCondition()

    def abort(self):
        self._abort = True
        self.resume()

    def pause(self):
        with QMutexLocker(self._pause_mutex):
            self._paused = True
        self.paused.emit()

    def resume(self):
        should_emit = False
        with QMutexLocker(self._pause_mutex):
            if self._paused:
                self._paused = False
                self._pause_condition.wakeAll()
                should_emit = True
        if should_emit:
            self.resumed.emit()

    def _wait_if_paused(self):
        locker = QMutexLocker(self._pause_mutex)
        while self._paused and not self._abort:
            self._pause_condition.wait(self._pause_mutex)

    def run(self):
        success = 0
        errors = 0
        total = len(self.pairs)

        for i, pair in enumerate(self.pairs):
            self._wait_if_paused()
            if self._abort:
                break

            base_pct = (i / total) * 100
            scale = 1.0 / total

            def _progress(pct, msg, _base=base_pct, _scale=scale):
                self._wait_if_paused()
                if self._abort:
                    raise InterruptedError("Render đã bị dừng")
                # Show current video percentage directly so progress bar updates continuously
                msg_with_batch = msg.replace(f"[{pair.index}]", f"[{pair.index}/{total}]")
                self.progress.emit(pct, msg_with_batch)

            def _log(line):
                self.log_line.emit(line)

            try:
                out = render_pair(pair, self.config, _progress, _log, should_abort=lambda: self._abort)
                self.pair_done.emit(pair.index, out)
                success += 1
            except InterruptedError:
                break
            except Exception as e:
                self.pair_error.emit(pair.index, str(e))
                errors += 1

        if self._abort:
            self.stopped.emit()
        else:
            self.all_done.emit(success, errors)


class PairingWorker(QThread):
    """Quick worker to scan folders and build pairs (can be slow on network drives)."""
    done = pyqtSignal(list)      # list[FilePair]
    error = pyqtSignal(str)

    def __init__(self, audio_folder: str, srt_folder: str, parent=None):
        super().__init__(parent)
        self.audio_folder = audio_folder
        self.srt_folder = srt_folder

    def run(self):
        try:
            pairs = build_pairs(self.audio_folder, self.srt_folder)
            self.done.emit(pairs)
        except Exception as e:
            self.error.emit(str(e))

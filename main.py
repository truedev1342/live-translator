"""Live Translator — reads Windows 11 Live Captions and translates in real time.

Left pane  : full caption transcript (accumulated, nothing dropped).
Right pane : translated transcript.
Controls   : translation engine, source/target language, optional API key, Clear.

Run:  python main.py
"""

from __future__ import annotations

import os
import sys
import threading

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from accumulator import CaptionAccumulator
from caption_reader import CaptionReader
from translator import ENGINES, LANGUAGES, Translator


def resource_path(name: str) -> str:
    """Path to a bundled resource, works both in dev and in a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

_SENTENCE_ENDS = ".?!。？！\n"
_MAX_PENDING = 220  # flush a commit chunk even without punctuation past this length


class TranslationWorker(QThread):
    """Background translator.

    Two kinds of work:
      * commit chunks  — stable text, translated once, results emitted in order.
      * tail           — the volatile on-screen text, latest-wins.
    """

    committedTranslated = pyqtSignal(str)  # append to the committed translation
    tailTranslated = pyqtSignal(str)       # replace the live tail translation
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._translator = Translator()
        self._config = None
        self._commits: list[str] = []
        self._tail = None
        self._lock = threading.Lock()
        self._running = True

    def configure(self, engine: str, source: str, target: str, api_key: str):
        self._config = (engine, source, target, api_key)

    def submit_commit(self, text: str):
        text = text.strip()
        if text:
            with self._lock:
                self._commits.append(text)

    def submit_tail(self, text: str):
        with self._lock:
            self._tail = text

    def reset(self):
        with self._lock:
            self._commits.clear()
            self._tail = None

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            if self._config is None:
                self.msleep(80)
                continue
            with self._lock:
                if self._commits:
                    job, kind = self._commits.pop(0), "commit"
                elif self._tail is not None:
                    job, kind, self._tail = self._tail, "tail", None
                else:
                    job = kind = None
            if job is None:
                self.msleep(80)
                continue
            try:
                self._translator.configure(*self._config)
                result = self._translator.translate(job)
                if kind == "commit":
                    self.committedTranslated.emit(result)
                else:
                    self.tailTranslated.emit(result)
            except Exception as exc:
                if kind == "commit":  # don't lose stable text — retry it later
                    with self._lock:
                        self._commits.insert(0, job)
                self.failed.emit(str(exc))
                self.msleep(500)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Translator")
        self.resize(1000, 560)

        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._acc = CaptionAccumulator()
        self._pending_commit = ""      # committed source text not yet translated
        self._trans_committed = ""     # accumulated translation of committed text
        self._tail_translation = ""    # translation of the current live tail

        self._reader = CaptionReader()
        self._reader.captionChanged.connect(self._on_caption)
        self._reader.status.connect(self._set_status)

        self._worker = TranslationWorker()
        self._worker.committedTranslated.connect(self._on_committed_translated)
        self._worker.tailTranslated.connect(self._on_tail_translated)
        self._worker.failed.connect(lambda e: self._set_status(f"Translate error: {e}"))
        self._worker.start()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(500)
        self._debounce.timeout.connect(self._translate_tail)

        self._build_ui()
        self._on_engine_changed(self.engine_combo.currentText())

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Engine:"))
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(ENGINES.keys())
        self.engine_combo.currentTextChanged.connect(self._on_engine_changed)
        controls.addWidget(self.engine_combo)

        controls.addWidget(QLabel("From:"))
        self.source_combo = QComboBox()
        self.source_combo.addItems(LANGUAGES.keys())
        self.source_combo.setCurrentText("Auto detect")
        controls.addWidget(self.source_combo)

        controls.addWidget(QLabel("→ To:"))
        self.target_combo = QComboBox()
        self.target_combo.addItems([n for n in LANGUAGES if n != "Auto detect"])
        self.target_combo.setCurrentText("Vietnamese")
        controls.addWidget(self.target_combo)

        self.key_label = QLabel("API key:")
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("required for API-key engines")
        controls.addWidget(self.key_label)
        controls.addWidget(self.key_edit, 1)

        self.toggle_btn = QPushButton("Start")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._toggle)
        controls.addWidget(self.toggle_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        controls.addWidget(self.clear_btn)

        root.addLayout(controls)

        panes = QHBoxLayout()
        font = QFont()
        font.setPointSize(13)

        left = QVBoxLayout()
        left.addWidget(QLabel("Caption (source)"))
        self.source_text = QPlainTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.setFont(font)
        left.addWidget(self.source_text)
        panes.addLayout(left)

        right = QVBoxLayout()
        right.addWidget(QLabel("Translation"))
        self.target_text = QPlainTextEdit()
        self.target_text.setReadOnly(True)
        self.target_text.setFont(font)
        right.addWidget(self.target_text)
        panes.addLayout(right)

        root.addLayout(panes, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "Idle. Click Start, then enable Live Captions (Win+Ctrl+L)."
        )

    # -- events ------------------------------------------------------------
    def _on_engine_changed(self, name: str):
        needs_key = ENGINES[name].needs_key
        self.key_label.setVisible(needs_key)
        self.key_edit.setVisible(needs_key)

    def _toggle(self, checked: bool):
        if checked:
            self.toggle_btn.setText("Stop")
            if not self._reader.isRunning():
                self._reader.start()
            self._set_status("Listening for Live Captions…")
        else:
            self.toggle_btn.setText("Start")
            self._reader.stop()
            self._set_status("Stopped.")

    def _clear(self):
        self._acc.clear()
        self._pending_commit = ""
        self._trans_committed = ""
        self._tail_translation = ""
        self._worker.reset()
        self.source_text.clear()
        self.target_text.clear()
        self._set_status("Cleared.")

    def _on_caption(self, text: str):
        committed = self._acc.add(text)
        self._set_text(self.source_text, self._acc.full_text)

        if committed:
            self._pending_commit += committed
            self._flush_commits()
        self._debounce.start()

    def _flush_commits(self):
        """Send completed sentences (or overlong runs) for one-time translation."""
        self._sync_config()
        while True:
            buf = self._pending_commit
            cut = max(buf.rfind(c) for c in _SENTENCE_ENDS)
            if cut < 0 and len(buf) < _MAX_PENDING:
                break
            if cut < 0:
                cut = len(buf) - 1  # no punctuation but too long — flush all
            chunk, self._pending_commit = buf[: cut + 1], buf[cut + 1:]
            self._worker.submit_commit(chunk)

    def _translate_tail(self):
        tail = self._pending_commit + self._acc.current
        if not tail.strip():
            return
        self._sync_config()
        self._worker.submit_tail(tail)

    def _sync_config(self):
        self._worker.configure(
            self.engine_combo.currentText(),
            LANGUAGES[self.source_combo.currentText()],
            LANGUAGES[self.target_combo.currentText()],
            self.key_edit.text().strip(),
        )

    def _on_committed_translated(self, text: str):
        if self._trans_committed and not self._trans_committed.endswith((" ", "\n")):
            self._trans_committed += " "
        self._trans_committed += text
        self._refresh_translation()

    def _on_tail_translated(self, text: str):
        self._tail_translation = text
        self._refresh_translation()

    def _refresh_translation(self):
        joined = self._trans_committed
        if joined and self._tail_translation and not joined.endswith((" ", "\n")):
            joined += " "
        joined += self._tail_translation
        self._set_text(self.target_text, joined)

    @staticmethod
    def _set_text(widget: QPlainTextEdit, text: str):
        widget.setPlainText(text)
        widget.moveCursor(widget.textCursor().MoveOperation.End)
        widget.ensureCursorVisible()

    def _set_status(self, msg: str):
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        self._reader.stop()
        self._worker.stop()
        self._reader.wait(1500)
        self._worker.wait(1500)
        super().closeEvent(event)


def main():
    # Make Windows use our icon in the taskbar (own AppUserModelID, not python's).
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("weedoo.tylt.livetranslator")
        except Exception:
            pass

    app = QApplication(sys.argv)
    icon_path = resource_path("icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

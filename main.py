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
from datetime import datetime

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


def transcripts_dir() -> str:
    """Folder where saved transcripts go (next to the exe / script)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "transcripts")
    os.makedirs(path, exist_ok=True)
    return path

class TranslationWorker(QThread):
    """Live translator: only the most recent request matters (latest-wins).

    This keeps the on-screen translation within ~1s of the caption. There is no
    per-sentence queue — a backlog there was what made the translation lag far
    behind the source during continuous speech.
    """

    translated = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._translator = Translator()
        self._config = None
        self._pending = None
        self._lock = threading.Lock()
        self._running = True

    def configure(self, engine: str, source: str, target: str, api_key: str):
        self._config = (engine, source, target, api_key)

    def submit(self, text: str):
        with self._lock:
            self._pending = text

    def reset(self):
        with self._lock:
            self._pending = None

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            with self._lock:
                job = self._pending
                self._pending = None
            if job is None or self._config is None:
                self.msleep(60)
                continue
            try:
                self._translator.configure(*self._config)
                self.translated.emit(self._translator.translate(job))
            except Exception as exc:
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
        self._last_src = None          # last text sent to translate (dedup)

        self._reader = CaptionReader()
        self._reader.captionChanged.connect(self._on_caption)
        self._reader.status.connect(self._set_status)

        self._worker = TranslationWorker()
        self._worker.translated.connect(self._on_translated)
        self._worker.failed.connect(lambda e: self._set_status(f"Translate error: {e}"))
        self._worker.start()

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
            "Idle. Start, enable Live Captions (Win+Ctrl+L). Stop saves the "
            "captions to a file and clears memory."
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
            self._save_and_reset()

    def _save_and_reset(self):
        """Write the captions to a file, then reset."""
        source = self._acc.full_text.strip()
        if not source:
            self._reset_session()
            self._set_status("Stopped. Nothing to save. Ready for a new start.")
            return

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(transcripts_dir(), f"transcript_{ts}.txt")
        header = (
            f"Live Translator transcript — {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"{self.source_combo.currentText()}\n"
        )
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)
                f.write("\n=== CAPTIONS ===\n")
                f.write(source + "\n")
        except Exception as exc:
            self._reset_session()
            self._set_status(f"Stopped. Save failed: {exc}")
            return

        self._reset_session()
        self._set_status(f"Stopped. Saved captions to {path}. Ready for a new start.")

    def _reset_session(self):
        """Wipe in-memory transcript state and clear the panes."""
        self._acc.clear()
        self._last_src = None
        self._worker.reset()
        self.source_text.clear()
        self.target_text.clear()

    def _clear(self):
        self._reset_session()
        self._set_status("Cleared (not saved).")

    def _on_caption(self, text: str):
        # Accumulate the full transcript in memory (for saving on Stop), but
        # display only the current on-screen caption (rolling, not the whole).
        self._acc.add(text)
        current = self._acc.current
        self._set_text(self.source_text, current)
        self._translate(current)

    def _translate(self, text: str):
        """Send the current caption for translation (latest-wins, deduped)."""
        text = text.strip()
        if not text or text == self._last_src:
            return
        self._last_src = text
        self._worker.configure(*self._current_config())
        self._worker.submit(text)

    def _current_config(self):
        return (
            self.engine_combo.currentText(),
            LANGUAGES[self.source_combo.currentText()],
            LANGUAGES[self.target_combo.currentText()],
            self.key_edit.text().strip(),
        )

    def _on_translated(self, text: str):
        self._set_text(self.target_text, text)

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

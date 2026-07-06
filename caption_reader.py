"""Reads live text out of the Windows 11 "Live Captions" app.

Windows 11 Live Captions (LiveCaptions.exe) has no public text API, so we
read its on-screen text through the UI Automation accessibility tree using the
`uiautomation` package. This runs in a background QThread that polls the
caption window a few times a second and emits new text.
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal


# The Live Captions top-level window is named "Live captions" (varies slightly
# by build/locale). We match loosely and also fall back to the process name.
_WINDOW_NAMES = ("Live captions", "Live Captions")
_PROCESS_NAME = "LiveCaptions.exe"


class CaptionReader(QThread):
    captionChanged = pyqtSignal(str)   # emitted with the current caption text
    status = pyqtSignal(str)           # human-readable status/errors

    def __init__(self, poll_interval: float = 0.3, parent=None):
        super().__init__(parent)
        self._poll = poll_interval
        self._running = False
        self._last_text = ""

    def stop(self):
        self._running = False

    # -- helpers -----------------------------------------------------------
    def _find_window(self, auto):
        """Return the Live Captions window control, or None if not found."""
        for name in _WINDOW_NAMES:
            win = auto.WindowControl(searchDepth=1, Name=name)
            if win.Exists(maxSearchSeconds=0.2):
                return win
        # Fallback: scan top-level windows for the LiveCaptions process.
        root = auto.GetRootControl()
        for win in root.GetChildren():
            try:
                proc = win.ProcessId
                name = auto.ProcessIdToProcessName(proc) if proc else ""
            except Exception:
                name = ""
            if name and name.lower() == _PROCESS_NAME.lower():
                return win
        return None

    def _extract_text(self, auto, window) -> str:
        """Walk the window subtree and return the caption text."""
        best = ""
        # Breadth-first walk; caption text lives in a Text/Document/Edit control.
        stack = list(window.GetChildren())
        guard = 0
        while stack and guard < 400:
            guard += 1
            ctrl = stack.pop()
            try:
                ctype = ctrl.ControlTypeName
            except Exception:
                continue
            if ctype in ("TextControl", "DocumentControl", "EditControl"):
                text = self._control_text(ctrl)
                if text and len(text) > len(best):
                    best = text
            try:
                stack.extend(ctrl.GetChildren())
            except Exception:
                pass
        return best.strip()

    @staticmethod
    def _control_text(ctrl) -> str:
        # Prefer the TextPattern value; fall back to the element Name.
        try:
            tp = ctrl.GetTextPattern()
            if tp:
                doc = tp.DocumentRange.GetText(-1)
                if doc and doc.strip():
                    return doc
        except Exception:
            pass
        try:
            return ctrl.Name or ""
        except Exception:
            return ""

    # -- thread body -------------------------------------------------------
    def run(self):
        self._running = True
        try:
            import uiautomation as auto
        except Exception as exc:  # pragma: no cover
            self.status.emit(f"uiautomation import failed: {exc}")
            return

        auto.SetGlobalSearchTimeout(0.5)
        announced_missing = False

        while self._running:
            try:
                window = self._find_window(auto)
                if window is None:
                    if not announced_missing:
                        self.status.emit(
                            "Live Captions window not found. Turn it on with "
                            "Win + Ctrl + L, then keep it open."
                        )
                        announced_missing = True
                    time.sleep(1.0)
                    continue

                if announced_missing:
                    self.status.emit("Connected to Live Captions.")
                    announced_missing = False

                text = self._extract_text(auto, window)
                if text and text != self._last_text:
                    self._last_text = text
                    self.captionChanged.emit(text)
            except Exception as exc:  # keep the loop alive on transient errors
                self.status.emit(f"Reader error: {exc}")
                time.sleep(0.5)

            time.sleep(self._poll)

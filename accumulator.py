"""Turns the rolling Live Captions window into a growing, de-duplicated transcript.

Live Captions only keeps the last few lines on screen. Each snapshot we read
overlaps the previous one, and the tail is often *revised* as recognition
improves (a provisional "the database." becomes "the database ingestion...").

Naive exact suffix/prefix de-overlap breaks on those revisions: when the
boundary text changes even slightly, no overlap is found and the whole snapshot
gets appended again, duplicating text (e.g. ABCD -> "AABABCABCD"). Instead we
find the overlap with a *fuzzy* longest-match (difflib) anchored at the
boundary, and replace the accumulated tail with the newer snapshot's version.
"""

from __future__ import annotations

import difflib

_MIN_ANCHOR = 6       # min chars of overlap needed to trust a boundary match
_BOUNDARY_SLACK = 8   # how far the anchor may sit from the window / snapshot edge


class CaptionAccumulator:
    def __init__(self):
        self._full = ""       # accumulated, de-duplicated transcript
        self._current = ""    # latest raw on-screen snapshot (for live display)

    def clear(self):
        self._full = ""
        self._current = ""

    @property
    def current(self) -> str:
        return self._current

    @property
    def full_text(self) -> str:
        return self._full

    def add(self, caption: str) -> None:
        caption = caption.strip()
        if not caption or caption == self._current:
            return
        self._current = caption
        self._full = self._merge(self._full, caption)

    @staticmethod
    def _merge(full: str, s: str) -> str:
        """Merge snapshot `s` into the transcript `full` without duplicating."""
        if not full:
            return s

        # Only the tail of `full` (a little longer than s) can overlap s.
        window_len = min(len(full), max(len(s) * 2, len(s) + 40))
        start = len(full) - window_len
        window = full[start:]

        # 1) Fuzzy boundary overlap — robust to revised words/punctuation in the
        #    caption tail. Replace full's tail with s's newer version.
        m = difflib.SequenceMatcher(None, window, s, autojunk=False).find_longest_match(
            0, len(window), 0, len(s)
        )
        near_full_end = (len(window) - (m.a + m.size)) <= _BOUNDARY_SLACK
        near_s_start = m.b <= _BOUNDARY_SLACK
        if m.size >= _MIN_ANCHOR and near_full_end and near_s_start:
            return full[: start + m.a] + s[m.b:]

        # 2) Exact suffix/prefix overlap — handles clean growth, incl. overlaps
        #    too short for the fuzzy anchor (e.g. "ABC" -> "ABCD").
        k = CaptionAccumulator._exact_overlap(window, s)
        if k > 0:
            return full[: len(full) - k] + s

        # 3) No overlap — the window scrolled to entirely new text.
        sep = "" if full.endswith((" ", "\n")) else " "
        return full + sep + s

    @staticmethod
    def _exact_overlap(a: str, s: str) -> int:
        """Largest k such that the last k chars of a equal the first k of s."""
        for k in range(min(len(a), len(s)), 0, -1):
            if a[-k:] == s[:k]:
                return k
        return 0

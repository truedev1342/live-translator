"""Turns the rolling Live Captions window into a growing, de-duplicated transcript.

Live Captions only keeps the last few lines on screen. Each snapshot we read
overlaps the previous one and the tail can be revised as speech is recognized.
This class merges snapshots into a full transcript without duplicating the
overlap, and separates the stable "committed" text (scrolled off screen) from
the volatile "current" tail that is still on screen and may still change.
"""

from __future__ import annotations


class CaptionAccumulator:
    def __init__(self):
        self._committed = ""   # text that has scrolled off screen (stable)
        self._current = ""     # latest on-screen caption snapshot (volatile)

    def clear(self):
        self._committed = ""
        self._current = ""

    @property
    def current(self) -> str:
        return self._current

    @property
    def committed(self) -> str:
        return self._committed

    @property
    def full_text(self) -> str:
        return self._committed + self._current

    def add(self, caption: str) -> str:
        """Merge a new caption snapshot.

        Returns the text (if any) that just became *committed* — i.e. scrolled
        off the top of the caption window this update. Empty string if nothing
        was committed.
        """
        caption = caption.strip()
        if not caption or caption == self._current:
            return ""
        if not self._current:
            self._current = caption
            return ""

        k = self._overlap(self._current, caption)
        if k == len(self._current):
            # New snapshot extends/revises the current one — nothing scrolled off.
            self._current = caption
            return ""

        # The part of the old snapshot before the overlap has scrolled away.
        scrolled_off = self._current[: len(self._current) - k]
        self._committed += scrolled_off
        self._current = caption
        return scrolled_off

    @staticmethod
    def _overlap(a: str, b: str) -> int:
        """Largest k such that the last k chars of a equal the first k of b."""
        maxk = min(len(a), len(b))
        for k in range(maxk, 0, -1):
            if a[-k:] == b[:k]:
                return k
        return 0

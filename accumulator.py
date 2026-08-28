"""Turns the rolling Live Captions window into a growing, de-duplicated transcript.

Live Captions shows a handful of lines at a time. Every snapshot we read repeats
the lines still on screen, drops the ones that scrolled off the top, and *revises*
the last line as recognition improves ("i'm gonna start is that right yeah" later
becomes "I'm gonna start. Is that right? Yeah. Well I'm ...").

Character-level de-overlap cannot survive that: once the revised tail differs by
more than a few characters, no overlap is found and the entire snapshot — all of
its still-on-screen lines — is appended again, so the transcript repeats itself.

So we work in lines instead. The transcript is kept as a list of lines; each
snapshot is aligned against the tail of that list by fuzzy line matching, and the
overlapping lines are *replaced* by the snapshot's newer wording. Only lines that
have scrolled out of the window are ever frozen.
"""

from __future__ import annotations

import difflib

_LINE_MATCH = 0.75      # similarity for two lines to count as the same line
_MIN_MATCH_RATIO = 0.6  # share of the compared text that must line up
_MIN_MATCH_CHARS = 10   # ignore anchors too small to trust (e.g. "Yeah.")
_SEARCH_SLACK = 5       # extra lines of tail to consider when aligning


def _norm(line: str) -> str:
    """Lowercase letters/digits only — punctuation and case are what get revised."""
    return "".join(c for c in line.lower() if c.isalnum() or c == " ").strip()


def _same_line(a: str, b: str) -> bool:
    """True if `a` and `b` are the same caption line, allowing for revision.

    The newer line is usually the older one continued, so only the shared leading
    part is compared.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return na == nb
    n = min(len(na), len(nb))
    if n < 4:
        return na[:n] == nb[:n]
    return difflib.SequenceMatcher(None, na[:n], nb[:n]).ratio() >= _LINE_MATCH


class CaptionAccumulator:
    def __init__(self):
        self._lines: list[str] = []   # accumulated, de-duplicated transcript
        self._current = ""            # latest raw on-screen snapshot (for display)

    def clear(self):
        self._lines = []
        self._current = ""

    @property
    def current(self) -> str:
        return self._current

    @property
    def full_text(self) -> str:
        return "\n".join(self._lines)

    def add(self, caption: str) -> None:
        caption = caption.strip()
        if not caption or caption == self._current:
            return
        self._current = caption
        snap = [ln.strip() for ln in caption.splitlines() if ln.strip()]
        if snap:
            self._lines = self._merge(self._lines, snap)

    @staticmethod
    def _merge(lines: list[str], snap: list[str]) -> list[str]:
        """Splice `snap` onto `lines`, replacing the lines it still shows."""
        if not lines:
            return list(snap)
        k = CaptionAccumulator._align(lines, snap)
        return lines[:k] + snap

    @staticmethod
    def _align(lines: list[str], snap: list[str]) -> int:
        """Index in `lines` where `snap` starts; len(lines) when nothing overlaps."""
        first = max(0, len(lines) - (len(snap) + _SEARCH_SLACK))
        best_k, best_hit = len(lines), 0
        for k in range(first, len(lines)):
            hit = total = pairs = matched = grown = 0
            for old, new in zip(lines[k:], snap):
                a, b = _norm(old), _norm(new)
                pairs += 1
                if _same_line(old, new):
                    matched += 1
                    hit += min(len(a), len(b))
                    total += min(len(a), len(b))
                    if b.startswith(a) or a.startswith(b):
                        grown += 1     # the line was simply carried on
                else:
                    total += max(len(a), len(b))
            # A short anchor is only trusted when every line it covers is the
            # same line carried on — that is how a snapshot's first line looks
            # while the transcript is still only a few words long.
            carried_on = pairs and matched == pairs and grown == pairs
            if not carried_on and (hit < _MIN_MATCH_CHARS or hit < total * _MIN_MATCH_RATIO):
                continue
            if hit > best_hit:      # strict: ties keep the longest overlap
                best_k, best_hit = k, hit
        return best_k

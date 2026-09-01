"""Turns the rolling Live Captions window into a growing, de-duplicated transcript.

Live Captions shows a handful of lines at a time. Every snapshot we read repeats
the lines still on screen, drops the ones that scrolled off the top, and *revises*
the last line as recognition improves ("i'm gonna start is that right yeah" later
becomes "I'm gonna start. Is that right? Yeah. Well I'm ...").

Character-level de-overlap cannot survive that: once the revised tail differs by
more than a few characters, no overlap is found and the entire snapshot — all of
its still-on-screen lines — is appended again, so the transcript repeats itself.

So we work in lines instead. The transcript is built as a list of lines; each
snapshot is aligned against the tail of that list by fuzzy line matching, and the
overlapping lines are *replaced* by the snapshot's newer wording. Only lines that
have scrolled out of the window are ever frozen.

Folding a snapshot in costs ~10 ms, far too much to spend on every caption while
the GUI is trying to show and translate it. So nothing is folded live: the app
just collects the raw snapshots and calls `build_transcript` when the session
stops. Almost all of those snapshots differ only in their last, still-being-typed
line, and each one supersedes the last, so they are pruned to the handful that
actually contribute lines before any merging happens.
"""

from __future__ import annotations

import difflib
from functools import lru_cache

_LINE_MATCH = 0.75      # similarity for two lines to count as the same line
_MIN_MATCH_RATIO = 0.6  # share of the compared text that must line up
_MIN_MATCH_CHARS = 10   # ignore anchors too small to trust (e.g. "Yeah.")
_SEARCH_SLACK = 5       # extra lines of tail to consider when aligning
_CMP_CHARS = 60         # a line's identity is settled well within its opening


@lru_cache(maxsize=8192)
def _norm(line: str) -> str:
    """Lowercase letters/digits only — punctuation and case are what get revised.

    Cached: alignment normalizes the same handful of lines over and over.
    """
    return "".join(c for c in line.lower() if c.isalnum() or c == " ").strip()


def _same_line(a: str, b: str) -> bool:
    """True if `a` and `b` are the same caption line, allowing for revision.

    The newer line is usually the older one continued, so only the shared leading
    part is compared — and only its first `_CMP_CHARS`, which is both cheaper and
    enough: no two caption lines open the same way by accident.
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return na == nb
    n = min(len(na), len(nb), _CMP_CHARS)
    if na[:n] == nb[:n]:        # unchanged, or simply carried on — the common case
        return True
    if n < 4:
        return False
    return difflib.SequenceMatcher(None, na[:n], nb[:n]).ratio() >= _LINE_MATCH


def build_transcript(snapshots) -> str:
    """Fold the caption snapshots captured during a session into one transcript."""
    lines: list[str] = []
    for snap in _prune(snapshots):
        lines = _merge(lines, snap)
    return "\n".join(lines)


def _prune(snapshots) -> list[list[str]]:
    """Drop snapshots a later one already covers, keeping only real checkpoints.

    While the caption window has not scrolled its first line stays put, so the
    newer snapshot shows everything the older one did (and shows it better). Only
    when that first line changes has text left the window for good.
    """
    kept: list[list[str]] = []
    for snap in snapshots:
        lines = [ln.strip() for ln in snap.splitlines() if ln.strip()]
        if not lines:
            continue
        if kept and len(lines) >= len(kept[-1]) and _same_line(kept[-1][0], lines[0]):
            kept[-1] = lines        # same window, further along — supersede
        else:
            kept.append(lines)
    return kept


def _merge(lines: list[str], snap: list[str]) -> list[str]:
    """Splice `snap` onto `lines`, replacing the lines it still shows."""
    if not lines:
        return list(snap)
    k = _align(lines, snap)
    return lines[:k] + snap


def _align(lines: list[str], snap: list[str]) -> int:
    """Index in `lines` where `snap` starts; len(lines) when nothing overlaps."""
    first = max(0, len(lines) - (len(snap) + _SEARCH_SLACK))
    offsets = range(first, len(lines))
    # The snapshot almost always still opens on a line the transcript has, so
    # score only those offsets; scoring every one costs several times as much.
    anchored = [k for k in offsets if _same_line(lines[k], snap[0])]
    best_k = _best_offset(lines, snap, anchored)
    if best_k == len(lines) and anchored:
        best_k = _best_offset(lines, snap, offsets)   # first line was rewritten
    return best_k


def _best_offset(lines: list[str], snap: list[str], offsets) -> int:
    """The offset whose lines line up with `snap` best; len(lines) if none do."""
    best_k, best_hit = len(lines), 0
    for k in offsets:
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

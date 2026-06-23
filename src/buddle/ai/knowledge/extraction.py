"""Knowledge unit extraction — pure, rule-based (no external calls).

A post's authored text (Post.content_transformed) is split into 1..5 atomic
"thought" units. Short posts yield one unit; posts carrying several distinct
thoughts yield up to `max_units`. This is the rule-based starting point agreed
in the design; an LLM extractor can later replace extract_units() behind the
same signature.

Why content_transformed (not content_raw): the reorganization space stores the
persona's *refined* expression, not the user's rough input, so the extracted
gists are clean sentences other personas can reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_UNITS = 5
_MIN_GIST_CHARS = 6  # ignore fragments shorter than this (noise)

# Sentence-ish boundary: Korean/English terminal punctuation or hard newlines.
# We keep it deliberately simple and deterministic.
_BOUNDARY_RE = re.compile(r"(?<=[.!?。…])\s+|[\n\r]+|(?<=[다요죠음])\s+(?=[A-Z가-힣])")


@dataclass(frozen=True, slots=True)
class RawUnit:
    """One extracted thought. `span` keeps the source offsets for traceability."""

    gist: str
    span: tuple[int, int]


def _split_segments(text: str) -> list[tuple[str, int, int]]:
    """Split into (segment, start, end) keeping original offsets."""
    segments: list[tuple[str, int, int]] = []
    pos = 0
    for piece in _BOUNDARY_RE.split(text):
        if piece is None:
            continue
        # find the piece's real offset from pos (split drops the delimiters)
        idx = text.find(piece, pos)
        if idx < 0:
            idx = pos
        start = idx
        end = idx + len(piece)
        pos = end
        seg = piece.strip()
        if seg:
            segments.append((seg, start, end))
    return segments


def extract_units(text: str, *, max_units: int = DEFAULT_MAX_UNITS) -> list[RawUnit]:
    """Extract 1..max_units atomic thought units from authored text.

    Deterministic: same input -> same units. Returns at least one unit for any
    non-empty text (the whole text as a single gist) and never more than
    max_units (longest/most-substantial segments win, original order kept).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    segments = _split_segments(cleaned)
    # Keep only segments with enough signal.
    candidates = [(s, a, b) for (s, a, b) in segments if len(s) >= _MIN_GIST_CHARS]

    if not candidates:
        # No clean sentence boundary (e.g. a short phrase) -> whole text is one unit.
        return [RawUnit(gist=cleaned, span=(0, len(cleaned)))]

    if len(candidates) <= max_units:
        return [RawUnit(gist=s, span=(a, b)) for (s, a, b) in candidates]

    # Too many segments: pick the `max_units` most substantial (by length),
    # then restore original order for readability/traceability.
    ranked = sorted(candidates, key=lambda c: len(c[0]), reverse=True)[:max_units]
    ranked_in_order = sorted(ranked, key=lambda c: c[1])
    return [RawUnit(gist=s, span=(a, b)) for (s, a, b) in ranked_in_order]

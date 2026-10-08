"""Document chunking.

Paragraph-aware splitting with a character budget and overlap. Documents in this
domain (emails, CSM notes, QBR summaries) are short and paragraph-structured, so
respecting paragraph boundaries keeps a complete thought — and therefore a
citable claim — inside one chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import get_settings

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    char_start: int
    char_end: int


def chunk_text(text: str, *, target_chars: int | None = None, overlap_chars: int | None = None) -> list[Chunk]:
    settings = get_settings()
    target = target_chars or settings.chunk_target_chars
    overlap = overlap_chars or settings.chunk_overlap_chars
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= target:
        return [Chunk(index=0, content=cleaned, char_start=0, char_end=len(cleaned))]

    units = _split_units(cleaned, target)
    chunks: list[Chunk] = []
    buffer = ""
    cursor = 0

    for unit in units:
        if buffer and len(buffer) + len(unit) + 2 > target:
            chunks.append(
                Chunk(index=len(chunks), content=buffer.strip(), char_start=cursor, char_end=cursor + len(buffer))
            )
            tail = buffer[-overlap:] if overlap else ""
            cursor += max(0, len(buffer) - len(tail))
            buffer = (tail + "\n\n" + unit) if tail else unit
        else:
            buffer = f"{buffer}\n\n{unit}" if buffer else unit

    if buffer.strip():
        chunks.append(
            Chunk(index=len(chunks), content=buffer.strip(), char_start=cursor, char_end=cursor + len(buffer))
        )
    return chunks


def _split_units(text: str, target: int) -> list[str]:
    """Paragraphs, further split into sentences when a paragraph is oversized."""
    units: list[str] = []
    for paragraph in _PARAGRAPH_RE.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= target:
            units.append(paragraph)
            continue
        current = ""
        for sentence in _SENTENCE_RE.split(paragraph):
            if current and len(current) + len(sentence) + 1 > target:
                units.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current.strip():
            units.append(current.strip())
    return units

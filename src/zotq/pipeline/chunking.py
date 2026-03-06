"""Chunking helpers for index ingestion."""

from __future__ import annotations

from ..models import ChunkRecord


def chunk_text(item_key: str, text: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[ChunkRecord]:
    clean = (text or "").strip()
    if not clean:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 4)

    chunks: list[ChunkRecord] = []
    start = 0
    ordinal = 0
    step = chunk_size - overlap

    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        piece = clean[start:end].strip()
        if piece:
            chunk_id = f"{item_key}:{ordinal}"
            chunks.append(ChunkRecord(chunk_id=chunk_id, item_key=item_key, ordinal=ordinal, text=piece))
            ordinal += 1
        if end >= len(clean):
            break
        start += step

    return chunks

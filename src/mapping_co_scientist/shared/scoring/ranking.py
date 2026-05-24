from __future__ import annotations

from typing import Protocol


class HasConfidence(Protocol):
    confidence: float
    rank: int | None


def rank_by_confidence(items: list[HasConfidence], top_k: int | None = None) -> list[HasConfidence]:
    """Sort items by confidence descending, assign rank attribute."""
    sorted_items = sorted(items, key=lambda x: x.confidence, reverse=True)
    if top_k is not None:
        if top_k < 0:
            raise ValueError("top_k must be >= 0")
        sorted_items = sorted_items[:top_k]
    for i, item in enumerate(sorted_items):
        item.rank = i + 1
    return sorted_items

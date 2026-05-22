from __future__ import annotations
from pydantic import BaseModel


class ConfidenceScore(BaseModel):
    score: float
    label: str
    method: str
    note: str | None = None

    @staticmethod
    def from_score(score: float, method: str = "aggregate") -> "ConfidenceScore":
        if score >= 0.85:
            label = "very_high"
        elif score >= 0.70:
            label = "high"
        elif score >= 0.50:
            label = "medium"
        elif score >= 0.30:
            label = "low"
        else:
            label = "very_low"
        return ConfidenceScore(score=score, label=label, method=method)

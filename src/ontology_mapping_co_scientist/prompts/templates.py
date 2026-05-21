"""
Versioned prompt templates for all LLM agents.

Storing prompts here (separate from agent code) allows independent auditing,
iteration, and hash-based reproducibility tracking.
"""
from __future__ import annotations

import hashlib

PROMPT_VERSION = "1.0.0"


def get_prompt_hash(prompt: str) -> str:
    """Return the first 12 characters of the SHA-256 of the prompt string.

    Args:
        prompt: The prompt text to hash.

    Returns:
        A 12-character hex string derived from the SHA-256 digest.
    """
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


ADVERSARIAL_REVIEWER_SYSTEM = (
    "You are an adversarial reviewer for ontology mappings. Your job is to find "
    "problems, ambiguities, and weaknesses in proposed mappings. Be critical but fair."
)

ONTOLOGY_ENGINEER_SYSTEM = (
    "You are an ontology engineer reviewing a proposed ontology mapping for logical "
    "correctness. Your job is to check predicate appropriateness, class/property "
    "compatibility, hierarchy placement, and domain/range constraints."
)

DOMAIN_SCIENTIST_SYSTEM = (
    "You are a domain scientist reviewing a proposed ontology mapping for scientific "
    "plausibility. Your job is to check whether the mapping makes sense in the "
    "real-world context of the research domain."
)

CANDIDATE_SCORER_SYSTEM = (
    "You are a semantic similarity expert. Your job is to score how well a source "
    "field semantically matches each candidate ontology term, on a scale of 0.0 to 1.0."
)

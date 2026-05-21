"""
TF-IDF based scoring of source entity descriptions against ontology term definitions.
Optionally uses sentence-transformers when available (graceful degradation to TF-IDF).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from ontology_mapping_co_scientist.models.entities import OntologyTerm
from ontology_mapping_co_scientist.models.mapping_hypothesis import Evidence

# ---------------------------------------------------------------------------
# Optional sklearn import with word-overlap fallback
# ---------------------------------------------------------------------------

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as _sklearn_cosine

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Index construction
# ---------------------------------------------------------------------------


def _term_document(term: OntologyTerm) -> str:
    """Build a single text document for a term by concatenating label and definition."""
    parts = [term.label]
    if term.definition:
        parts.append(term.definition)
    parts.extend(term.synonyms)
    return " ".join(parts)


def build_tfidf_index(terms: list[OntologyTerm]) -> dict:
    """Build a TF-IDF index over all term definitions and labels.

    Uses sklearn's TfidfVectorizer when sklearn is available.  Falls back to a
    simple word-overlap (Counter-based) index otherwise.

    Args:
        terms: List of ontology terms to index.

    Returns:
        A dict with the keys needed by :func:`score_definition_similarity`.
        When sklearn is available the dict contains::

            {
                "backend": "tfidf",
                "vectorizer": TfidfVectorizer,
                "matrix": sparse matrix (n_terms x vocab),
                "terms": list[OntologyTerm],
            }

        When sklearn is unavailable the dict contains::

            {
                "backend": "word_overlap",
                "term_counters": list[Counter],  # parallel to ``terms``
                "terms": list[OntologyTerm],
            }
    """
    if not terms:
        if _SKLEARN_AVAILABLE:
            return {"backend": "tfidf", "vectorizer": None, "matrix": None, "terms": []}
        return {"backend": "word_overlap", "term_counters": [], "terms": []}

    documents = [_term_document(t) for t in terms]

    if _SKLEARN_AVAILABLE:
        vectorizer = TfidfVectorizer(
            analyzer="word",
            token_pattern=r"(?u)\b\w+\b",
            lowercase=True,
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(documents)
        return {
            "backend": "tfidf",
            "vectorizer": vectorizer,
            "matrix": matrix,
            "terms": terms,
        }
    else:
        # Word-overlap fallback: store a Counter of tokens per term document
        counters = [Counter(doc.lower().split()) for doc in documents]
        return {
            "backend": "word_overlap",
            "term_counters": counters,
            "terms": terms,
        }


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------


def _cosine_counter(counter_a: Counter, counter_b: Counter) -> float:
    """Compute cosine similarity between two word-frequency Counter objects."""
    if not counter_a or not counter_b:
        return 0.0
    dot = sum(counter_a[w] * counter_b[w] for w in counter_a if w in counter_b)
    norm_a = math.sqrt(sum(v * v for v in counter_a.values()))
    norm_b = math.sqrt(sum(v * v for v in counter_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def score_definition_similarity(
    source_text: str,
    term: OntologyTerm,
    index: dict,
) -> float:
    """Return cosine similarity between source_text and term's entry in the index.

    Args:
        source_text: Free-text description from the source entity (label +
            description concatenated by the caller).
        term: The ontology term whose indexed document to compare against.
        index: The pre-built index returned by :func:`build_tfidf_index`.

    Returns:
        A float in ``[0.0, 1.0]``.  Returns ``0.0`` when the term is not in
        the index or when either text is empty.
    """
    if not source_text or not index.get("terms"):
        return 0.0

    terms = index["terms"]
    try:
        term_idx = next(i for i, t in enumerate(terms) if t.term_id == term.term_id)
    except StopIteration:
        return 0.0

    backend = index.get("backend", "word_overlap")

    if backend == "tfidf":
        vectorizer = index.get("vectorizer")
        matrix = index.get("matrix")
        if vectorizer is None or matrix is None:
            return 0.0
        source_vec = vectorizer.transform([source_text])
        term_vec = matrix[term_idx]
        sim = _sklearn_cosine(source_vec, term_vec)[0][0]
        return float(max(0.0, min(1.0, sim)))
    else:
        # Word-overlap fallback
        term_counters = index.get("term_counters", [])
        if not term_counters or term_idx >= len(term_counters):
            return 0.0
        source_counter = Counter(source_text.lower().split())
        return float(max(0.0, min(1.0, _cosine_counter(source_counter, term_counters[term_idx]))))


# ---------------------------------------------------------------------------
# Semantic embedding (optional)
# ---------------------------------------------------------------------------


def try_semantic_embedding(
    source_text: str,
    term_texts: list[str],
) -> list[float] | None:
    """Attempt to compute semantic cosine similarities using sentence-transformers.

    Uses the ``all-MiniLM-L6-v2`` model.  Returns ``None`` if
    ``sentence_transformers`` is not installed or if any error occurs during
    encoding/scoring.

    Args:
        source_text: The source entity text to embed.
        term_texts: A list of ontology term texts to compare against.

    Returns:
        A list of floats (one per entry in *term_texts*) in ``[0.0, 1.0]``, or
        ``None`` if ``sentence_transformers`` is unavailable.
    """
    try:
        from sentence_transformers import SentenceTransformer, util  # type: ignore[import]
    except ImportError:
        return None

    try:
        model = SentenceTransformer("all-MiniLM-L6-v2")
        source_emb = model.encode(source_text, convert_to_tensor=True)
        term_embs = model.encode(term_texts, convert_to_tensor=True)
        scores = util.cos_sim(source_emb, term_embs)[0].tolist()
        return [float(max(0.0, min(1.0, s))) for s in scores]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Evidence factory
# ---------------------------------------------------------------------------


def build_definition_evidence(
    source_label: str,
    term: OntologyTerm,
    score: float,
    method: str,
) -> Evidence:
    """Create an Evidence item from a definition-based similarity score.

    Args:
        source_label: Human-readable label of the source entity.
        term: The matched ontology term.
        score: Similarity score in ``[0.0, 1.0]``.
        method: Identifier for the method used, e.g. ``"tfidf"`` or
            ``"semantic_embedding"``.  Used to set ``evidence_type`` and
            ``source``.

    Returns:
        An :class:`~ontology_mapping_co_scientist.models.mapping_hypothesis.Evidence`
        instance.
    """
    if method == "semantic_embedding":
        evidence_type = "semantic_embedding"
    else:
        evidence_type = "definition_tfidf"

    clamped = max(0.0, min(1.0, score))
    description = (
        f"Definition similarity ({method}) between source '{source_label}' "
        f"and term '{term.label}' ({term.term_id}): {clamped:.3f}"
    )
    return Evidence(
        evidence_type=evidence_type,
        description=description,
        score=clamped,
        source=method,
    )

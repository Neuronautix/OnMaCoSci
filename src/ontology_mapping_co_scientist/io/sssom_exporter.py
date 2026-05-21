"""
Exports mapping hypotheses as SSSOM-compliant TSV files.

SSSOM (Simple Standard for Sharing Ontological Mappings) is a community standard
for representing mappings between entities in different ontologies or schemas.
See: https://mapping-commons.github.io/sssom/

This exporter targets SSSOM 0.15.x. The output includes:
- A YAML metadata block (prefixed with #) as the SSSOM header
- A TSV data section with required and recommended columns
- Correct SKOS predicate IRIs (full URIs, not CURIEs in the data rows)
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from ontology_mapping_co_scientist.models.mapping_hypothesis import (
    MappingHypothesis,
    MappingPredicate,
)

# ---------------------------------------------------------------------------
# SSSOM predicate URI mapping
# ---------------------------------------------------------------------------

PREDICATE_URIS: dict[str, str] = {
    "skos:exactMatch":   "http://www.w3.org/2004/02/skos/core#exactMatch",
    "skos:closeMatch":   "http://www.w3.org/2004/02/skos/core#closeMatch",
    "skos:broadMatch":   "http://www.w3.org/2004/02/skos/core#broadMatch",
    "skos:narrowMatch":  "http://www.w3.org/2004/02/skos/core#narrowMatch",
    "skos:relatedMatch": "http://www.w3.org/2004/02/skos/core#relatedMatch",
    "custom:requiresTransform": "https://w3id.org/omcs/mapping#requiresTransform",
    "custom:noMapping":         "https://w3id.org/omcs/mapping#noMapping",
}

# ---------------------------------------------------------------------------
# Mapping justification mapping (SSSOM uses semapv: vocabulary)
# ---------------------------------------------------------------------------

JUSTIFICATION_URIS: dict[str, str] = {
    "lexical_similarity": "semapv:LexicalSimilarityThresholdMatching",
    "definition_tfidf":   "semapv:SemanticSimilarityThresholdMatching",
    "semantic_embedding": "semapv:SemanticSimilarityThresholdMatching",
    "synonym_match":      "semapv:LexicalSimilarityThresholdMatching",
    "llm_adversarial":    "semapv:MappingReview",
    "default":            "semapv:ManualMappingCuration",
}

# SSSOM columns in required order
_FIELDNAMES = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "author_id",
    "mapping_date",
    "confidence",
    "subject_source",
    "object_source",
    "comment",
    "mapping_set_id",
]


def _resolve_justification(evidence_type: str) -> str:
    """Map an evidence_type string to a semapv: justification URI.

    Performs a best-prefix match: tries the full key first, then checks
    whether any known key is a substring of the provided evidence_type,
    and finally falls back to ``semapv:ManualMappingCuration``.

    Args:
        evidence_type: The ``evidence_type`` string from an
            :class:`~.Evidence` item.

    Returns:
        A ``semapv:`` CURIE string.
    """
    if evidence_type in JUSTIFICATION_URIS:
        return JUSTIFICATION_URIS[evidence_type]
    # Substring / prefix matching for compound evidence type names
    for key, uri in JUSTIFICATION_URIS.items():
        if key != "default" and key in evidence_type:
            return uri
    return JUSTIFICATION_URIS["default"]


def _build_yaml_header(
    mapping_set_id: str,
    today: str,
    subject_source: str,
    object_source: str,
    author_id: str,
) -> list[str]:
    """Build the SSSOM YAML metadata block as a list of ``#``-prefixed lines.

    Args:
        mapping_set_id: The mapping set identifier used in the IRI.
        today: ISO-format date string (``YYYY-MM-DD``).
        subject_source: Source file or URL of the first hypothesis's source
            entity, or ``"unknown"`` when not available.
        object_source: Ontology source URL/ID of the first hypothesis's
            target entity, or ``"unknown"`` when not available.
        author_id: The author/creator IRI to embed in the header.

    Returns:
        A list of strings, each starting with ``#``, representing the YAML
        metadata block.
    """
    lines = [
        "# ---",
        f"# mapping_set_id: https://w3id.org/omcs/mappings/{mapping_set_id}",
        '# mapping_set_version: "0.1.0"',
        "# license: https://creativecommons.org/licenses/by/4.0/",
        '# mapping_set_title: "Ontology Mapping Co-Scientist Output"',
        f"# creator_id: {author_id}",
        f"# mapping_date: {today}",
        f"# subject_source: {subject_source}",
        f"# object_source: {object_source}",
        "# curie_map:",
        "#   skos: http://www.w3.org/2004/02/skos/core#",
        "#   semapv: https://w3id.org/semapv/vocab/",
        "#   omcs: https://w3id.org/omcs/mapping#",
        "# ---",
    ]
    return lines


def _select_top_ranked(hypotheses: list[MappingHypothesis]) -> list[MappingHypothesis]:
    """Return only the highest-ranked hypothesis per subject_id.

    If *all* hypotheses have ``rank=None``, every hypothesis is included
    (no filtering is applied).  Otherwise, for each ``subject_id`` only the
    hypothesis with the lowest rank number (best rank = 1) is kept.  When
    multiple hypotheses share the same subject and the same lowest rank, the
    first one encountered is used.

    Args:
        hypotheses: The full list of hypotheses to filter.

    Returns:
        A (potentially shorter) list of hypotheses.
    """
    all_none = all(h.rank is None for h in hypotheses)
    if all_none:
        return list(hypotheses)

    # Group by subject_id, keeping the minimum rank (1 = best)
    best: dict[str, MappingHypothesis] = {}
    for h in hypotheses:
        sid = h.source_entity.entity_id
        if sid not in best:
            best[sid] = h
        else:
            current_rank = best[sid].rank if best[sid].rank is not None else float("inf")
            new_rank = h.rank if h.rank is not None else float("inf")
            if new_rank < current_rank:
                best[sid] = h
    return list(best.values())


def export_to_sssom(
    hypotheses: list[MappingHypothesis],
    output_path: str | Path,
    mapping_set_id: str | None = None,
    author_id: str = "https://w3id.org/omcs/agent/CandidateGeneratorAgent",
    include_no_mapping: bool = False,
) -> None:
    """Export a list of mapping hypotheses as a fully SSSOM-compliant TSV file.

    The output file begins with a YAML metadata block (each line prefixed
    with ``#``), followed by a tab-separated header row and one data row per
    hypothesis that passes the active filters.

    Filtering behaviour:

    * ``custom:noMapping`` hypotheses are excluded unless
      ``include_no_mapping=True``.
    * When any hypothesis carries a ``rank`` value, only the hypothesis with
      the lowest rank number per ``subject_id`` (i.e. rank = 1) is exported.
      When *no* hypothesis has a rank, all are exported.

    Column mapping:

    =================== =====================================================
    subject_id          ``source_entity.entity_id``
    subject_label       ``source_entity.label``
    predicate_id        Full SKOS/custom IRI from :data:`PREDICATE_URIS`
    object_id           ``target_entity.term_id``
    object_label        ``target_entity.label``
    mapping_justification  ``semapv:`` CURIE from :data:`JUSTIFICATION_URIS`
    author_id           ``author_id`` parameter
    mapping_date        Today's date in ``YYYY-MM-DD`` form
    confidence          ``hypothesis.confidence`` rounded to 4 decimal places
    subject_source      ``source_entity.source_file`` or ``""``
    object_source       ``target_entity.ontology_source`` or
                        ``target_entity.ontology_id`` or ``""``
    comment             Up to 3 warnings joined by ``"; "``, or ``""``
    mapping_set_id      IRI of the mapping set
    =================== =====================================================

    Args:
        hypotheses: List of :class:`~.MappingHypothesis` objects to export.
        output_path: Destination file path.  The parent directory must
            already exist.  Any existing file at this path is overwritten.
        mapping_set_id: Optional identifier for the mapping set.  Defaults
            to the ``pipeline_run_id`` of the first hypothesis, or
            ``"unknown"`` when not available.
        author_id: IRI identifying the author or agent that produced these
            mappings.
        include_no_mapping: When ``True``, hypotheses with predicate
            ``custom:noMapping`` are included in the output.  Defaults to
            ``False`` because SSSOM does not define a standard no-mapping
            predicate.

    Returns:
        None.  The file is written to *output_path*.

    Raises:
        OSError: If the output file cannot be written.
    """
    output_path = Path(output_path)
    today = date.today().isoformat()

    # ------------------------------------------------------------------
    # Filter: exclude NO_MAPPING unless caller opts in
    # ------------------------------------------------------------------
    if not include_no_mapping:
        hypotheses = [
            h for h in hypotheses
            if h.predicate != MappingPredicate.NO_MAPPING
        ]

    # ------------------------------------------------------------------
    # Filter: keep only the top-ranked hypothesis per subject_id
    # ------------------------------------------------------------------
    hypotheses = _select_top_ranked(hypotheses)

    # ------------------------------------------------------------------
    # Derive header metadata from the first hypothesis (if any)
    # ------------------------------------------------------------------
    if hypotheses:
        first = hypotheses[0]
        subject_source = first.source_entity.source_file or "unknown"
        object_source = (
            first.target_entity.ontology_source
            or first.target_entity.ontology_id
            or "unknown"
        )
        resolved_set_id = (
            mapping_set_id
            or (first.provenance.pipeline_run_id if first.provenance.pipeline_run_id else None)
            or "unknown"
        )
    else:
        subject_source = "unknown"
        object_source = "unknown"
        resolved_set_id = mapping_set_id or "unknown"

    # ------------------------------------------------------------------
    # Write output
    # ------------------------------------------------------------------
    header_lines = _build_yaml_header(
        mapping_set_id=resolved_set_id,
        today=today,
        subject_source=subject_source,
        object_source=object_source,
        author_id=author_id,
    )

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        # Write YAML comment block
        for line in header_lines:
            fh.write(line + "\n")

        writer = csv.DictWriter(
            fh,
            fieldnames=_FIELDNAMES,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()

        for h in hypotheses:
            # Predicate: full URI
            predicate_id = PREDICATE_URIS.get(
                str(h.predicate.value), str(h.predicate.value)
            )

            # Mapping justification: map first evidence type via semapv vocab
            if h.evidence:
                justification = _resolve_justification(h.evidence[0].evidence_type)
            else:
                justification = JUSTIFICATION_URIS["default"]

            # Object source: prefer ontology_source URL, fall back to ontology_id
            obj_source = (
                h.target_entity.ontology_source
                or h.target_entity.ontology_id
                or ""
            )

            # Comment: up to 3 warnings
            comment = "; ".join(h.warnings[:3]) if h.warnings else ""

            # Mapping set id per row (consistent with header)
            row_set_id = (
                mapping_set_id
                or (h.provenance.pipeline_run_id if h.provenance.pipeline_run_id else None)
                or "unknown"
            )

            row: dict[str, str] = {
                "subject_id": h.source_entity.entity_id,
                "subject_label": h.source_entity.label,
                "predicate_id": predicate_id,
                "object_id": h.target_entity.term_id,
                "object_label": h.target_entity.label,
                "mapping_justification": justification,
                "author_id": author_id,
                "mapping_date": today,
                "confidence": str(round(h.confidence, 4)),
                "subject_source": h.source_entity.source_file or "",
                "object_source": obj_source,
                "comment": comment,
                "mapping_set_id": f"https://w3id.org/omcs/mappings/{row_set_id}",
            }
            writer.writerow(row)

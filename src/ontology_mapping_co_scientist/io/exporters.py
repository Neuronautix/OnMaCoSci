"""Export functions for the Ontology Mapping Co-Scientist system.

Provides two serialisation targets for a list of :class:`MappingHypothesis`
objects:

* :func:`export_to_json` – a structured JSON file with a metadata envelope
  suitable for programmatic consumption and archiving.
* :func:`export_to_sssom_tsv` – a tab-separated file inspired by the Simple
  Standard for Sharing Ontological Mappings (SSSOM,
  https://mapping-commons.github.io/sssom/) that can be imported into many
  ontology tooling workflows.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ontology_mapping_co_scientist.models.mapping_hypothesis import MappingHypothesis

# ---------------------------------------------------------------------------
# SSSOM-inspired predicate ID mapping
# ---------------------------------------------------------------------------

_PREDICATE_TO_SSSOM: dict[str, str] = {
    "skos:exactMatch": "skos:exactMatch",
    "skos:closeMatch": "skos:closeMatch",
    "skos:broadMatch": "skos:broadMatch",
    "skos:narrowMatch": "skos:narrowMatch",
    "skos:relatedMatch": "skos:relatedMatch",
    "custom:requiresTransform": "sssom:MappingSetExpansion",
    "custom:noMapping": "sssom:NoMapping",
}

_PIPELINE_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_to_json(
    hypotheses: list[MappingHypothesis],
    output_path: str | Path,
) -> None:
    """Serialise a list of mapping hypotheses to a pretty-printed JSON file.

    The output document has the following top-level structure::

        {
          "metadata": {
            "generated_at": "<ISO 8601 UTC datetime>",
            "total_mappings": <int>,
            "pipeline_version": "0.1.0"
          },
          "mappings": [
            { ... pydantic model_dump of MappingHypothesis ... },
            ...
          ]
        }

    All Pydantic models are serialised via :meth:`~pydantic.BaseModel.model_dump`
    with ``mode="json"`` so that enum values, nested models, and custom types are
    converted to JSON-native representations automatically.

    Args:
        hypotheses: Ordered list of :class:`MappingHypothesis` objects to export.
        output_path: Destination file path.  Parent directories must already
            exist.  Any existing file at this path will be overwritten.

    Returns:
        None.  The file is written to *output_path*.

    Raises:
        OSError: If the file cannot be written (e.g. permission error).
    """
    output_path = Path(output_path)

    generated_at: str = datetime.now(tz=timezone.utc).isoformat()

    metadata: dict[str, Any] = {
        "generated_at": generated_at,
        "total_mappings": len(hypotheses),
        "pipeline_version": _PIPELINE_VERSION,
    }

    mappings: list[dict[str, Any]] = [
        h.model_dump(mode="json") for h in hypotheses
    ]

    document: dict[str, Any] = {
        "metadata": metadata,
        "mappings": mappings,
    }

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=False)
        fh.write("\n")  # POSIX trailing newline


def export_to_sssom_tsv(
    hypotheses: list[MappingHypothesis],
    output_path: str | Path,
) -> None:
    """Export mapping hypotheses as an SSSOM-inspired TSV file.

    The output is a plain tab-separated file with a leading block of comment
    lines (``#``-prefixed) describing the format, followed by a header row and
    one data row per hypothesis.

    Column definitions
    ------------------
    ================= =========================================================
    mapping_id        Unique identifier for this hypothesis.
    subject_id        ``source_entity.entity_id``
    subject_label     ``source_entity.label``
    predicate_id      SKOS / custom predicate value (e.g. ``skos:exactMatch``).
    object_id         ``target_entity.term_id``
    object_label      ``target_entity.label``
    confidence        Aggregate confidence score (0.0–1.0).
    mapping_justification  Description of the first supporting evidence item,
                           or ``"LexicalSimilarity"`` when no evidence is
                           recorded.
    comment           Semicolon-separated pipeline warnings, or empty string.
    ================= =========================================================

    The file is encoded as UTF-8 with Unix line endings (``\\n``).  The SSSOM
    specification (https://mapping-commons.github.io/sssom/) describes a richer
    format; this export provides a practical, tooling-compatible subset.

    Args:
        hypotheses: Ordered list of :class:`MappingHypothesis` objects to export.
        output_path: Destination file path.  Parent directories must already
            exist.  Any existing file at this path will be overwritten.

    Returns:
        None.  The file is written to *output_path*.

    Raises:
        OSError: If the file cannot be written.
    """
    output_path = Path(output_path)

    _COMMENT_LINES = [
        "# SSSOM-inspired Mapping Export",
        "# Generated by: Ontology Mapping Co-Scientist v" + _PIPELINE_VERSION,
        "#",
        "# This file follows the spirit of the Simple Standard for Sharing",
        "# Ontological Mappings (SSSOM): https://mapping-commons.github.io/sssom/",
        "# It is not a fully conformant SSSOM file; some fields are omitted or",
        "# use pipeline-internal identifiers.",
        "#",
        "# Column descriptions:",
        "#   mapping_id            - Unique identifier for this mapping hypothesis",
        "#   subject_id            - Source entity identifier (e.g. csv:animal.strain)",
        "#   subject_label         - Human-readable label of the source entity",
        "#   predicate_id          - SKOS mapping predicate (e.g. skos:exactMatch)",
        "#   object_id             - Target ontology term CURIE or IRI",
        "#   object_label          - Preferred label of the ontology term",
        "#   confidence            - Aggregate confidence score [0.0, 1.0]",
        "#   mapping_justification - Evidence description or 'LexicalSimilarity'",
        "#   comment               - Pipeline warnings (semicolon-separated), if any",
        "#",
    ]

    _FIELDNAMES = [
        "mapping_id",
        "subject_id",
        "subject_label",
        "predicate_id",
        "object_id",
        "object_label",
        "confidence",
        "mapping_justification",
        "comment",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        # Write comment block
        for line in _COMMENT_LINES:
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
            # Mapping justification: first evidence description, or fallback
            if h.evidence:
                justification = h.evidence[0].description
            else:
                justification = "LexicalSimilarity"

            # Warnings joined by "; "
            comment = "; ".join(h.warnings) if h.warnings else ""

            # Normalise predicate to SSSOM vocabulary where possible
            predicate_id = _PREDICATE_TO_SSSOM.get(
                str(h.predicate), str(h.predicate)
            )

            row: dict[str, str] = {
                "mapping_id": h.mapping_id,
                "subject_id": h.source_entity.entity_id,
                "subject_label": h.source_entity.label,
                "predicate_id": predicate_id,
                "object_id": h.target_entity.term_id,
                "object_label": h.target_entity.label,
                "confidence": f"{h.confidence:.4f}",
                "mapping_justification": justification,
                "comment": comment,
            }
            writer.writerow(row)


def export_to_sssom_compliant(
    hypotheses: list[MappingHypothesis],
    output_path: str | Path,
    **kwargs,
) -> None:
    """Exports using the full SSSOM-compliant format. See sssom_exporter module."""
    from ontology_mapping_co_scientist.io.sssom_exporter import export_to_sssom
    export_to_sssom(hypotheses, output_path, **kwargs)

"""Source profiler agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`SourceProfilerAgent`, which is responsible for
loading and profiling source entities from supported input file formats.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from ontology_mapping_co_scientist.io.csv_loader import load_csv_entities
from ontology_mapping_co_scientist.io.json_schema_loader import load_json_schema_entities
from ontology_mapping_co_scientist.io.openapi_loader import load_openapi_entities
from ontology_mapping_co_scientist.io.rdf_ontology_loader import load_rdf_ontology
from ontology_mapping_co_scientist.models.entities import OntologyTerm, SourceEntity

logger = logging.getLogger(__name__)


class SourceProfilerAgent:
    """Extracts and profiles source entities from input schema files."""

    def profile_csv(self, filepath: str | Path) -> list[SourceEntity]:
        """Load source entities from a CSV file.

        Delegates to :func:`~ontology_mapping_co_scientist.io.csv_loader.load_csv_entities`
        and logs the number of entities discovered.

        Args:
            filepath: Path to the CSV file.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
            objects, one per data column.

        Raises:
            FileNotFoundError: If *filepath* does not exist.
            ValueError: If the CSV has no header or no data rows.
        """
        filepath = Path(filepath)
        logger.info("Profiling CSV file: %s", filepath)
        entities = load_csv_entities(filepath)
        logger.info("Discovered %d source entities from CSV: %s", len(entities), filepath)
        return entities

    def profile_openapi(self, filepath: str | Path) -> list[SourceEntity]:
        """Load source entities from an OpenAPI/JSON Schema file.

        Delegates to
        :func:`~ontology_mapping_co_scientist.io.openapi_loader.load_openapi_entities`
        and logs the number of entities discovered.

        Args:
            filepath: Path to the OpenAPI or JSON Schema file.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
            objects extracted from the schema.

        Raises:
            FileNotFoundError: If *filepath* does not exist.
            ValueError: If the file cannot be parsed as a valid schema.
        """
        filepath = Path(filepath)
        logger.info("Profiling OpenAPI/JSON Schema file: %s", filepath)
        entities = load_openapi_entities(filepath)
        logger.info(
            "Discovered %d source entities from OpenAPI schema: %s",
            len(entities),
            filepath,
        )
        return entities

    def profile_json_schema(self, filepath: str | Path) -> list[SourceEntity]:
        """Load source entities from a JSON Schema file.

        Delegates to
        :func:`~ontology_mapping_co_scientist.io.json_schema_loader.load_json_schema_entities`
        and logs the number of entities discovered.

        Args:
            filepath: Path to the JSON Schema file.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
            objects extracted from the schema properties.

        Raises:
            FileNotFoundError: If *filepath* does not exist.
            ValueError: If the file cannot be parsed as JSON.
        """
        filepath = Path(filepath)
        logger.info("Profiling JSON Schema file: %s", filepath)
        entities = load_json_schema_entities(filepath)
        logger.info(
            "Discovered %d source entities from JSON Schema: %s",
            len(entities),
            filepath,
        )
        return entities

    def profile_rdf(self, filepath: str | Path) -> list[SourceEntity]:
        """Load source entities from an RDF/OWL ontology file.

        Each :class:`~ontology_mapping_co_scientist.models.entities.OntologyTerm`
        loaded from the RDF graph is converted to a
        :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
        with ``source_type="rdf"``.

        Args:
            filepath: Path to the RDF/OWL file.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
            objects, one per ontology term.

        Raises:
            ImportError: If rdflib is not installed.
            FileNotFoundError: If *filepath* does not exist.
        """
        filepath = Path(filepath)
        logger.info("Profiling RDF/OWL file as source entities: %s", filepath)
        terms: list[OntologyTerm] = load_rdf_ontology(filepath)
        entities: list[SourceEntity] = []
        for term in terms:
            entity = SourceEntity(
                entity_id=f"rdf:{term.term_id}",
                label=term.label,
                description=term.definition,
                datatype=None,
                examples=list(term.synonyms[:3]),
                source_file=str(filepath),
                source_type="rdf",
                extra_context={
                    "term_id": term.term_id,
                    "term_type": term.term_type,
                    "ontology_id": term.ontology_id,
                    "parent_terms": term.parent_terms,
                },
            )
            entities.append(entity)
        logger.info(
            "Converted %d RDF terms to source entities from: %s",
            len(entities),
            filepath,
        )
        return entities

    def profile_auto(self, filepath: str | Path) -> list[SourceEntity]:
        """Automatically detect the file format by extension and profile accordingly.

        Supported extensions:
        - ``.csv`` — delegates to :meth:`profile_csv`
        - ``.json`` — delegates to :meth:`profile_openapi`

        Args:
            filepath: Path to the source file.

        Returns:
            A list of :class:`~ontology_mapping_co_scientist.models.entities.SourceEntity`
            objects.

        Raises:
            ValueError: If the file extension is not recognised.
            FileNotFoundError: If *filepath* does not exist.
        """
        filepath = Path(filepath)
        suffix = filepath.suffix.lower()
        logger.debug("Auto-detecting format for file: %s (suffix=%r)", filepath, suffix)

        if suffix == ".csv":
            return self.profile_csv(filepath)
        elif suffix == ".json":
            # Distinguish JSON Schema from OpenAPI by checking for "$schema" key
            try:
                with filepath.open(encoding="utf-8") as fh:
                    doc = json.load(fh)
                if isinstance(doc, dict) and "$schema" in doc:
                    logger.debug(
                        "Detected JSON Schema file (has '$schema' key): %s", filepath
                    )
                    return self.profile_json_schema(filepath)
            except (json.JSONDecodeError, OSError):
                pass
            return self.profile_openapi(filepath)
        else:
            raise ValueError(
                f"Unsupported file extension {suffix!r} for auto-profiling. "
                "Supported: '.csv', '.json'."
            )

    def summarize(self, entities: list[SourceEntity]) -> dict:
        """Compute a statistical summary over a list of source entities.

        Args:
            entities: The list of source entities to summarise.

        Returns:
            A dictionary with the following keys:

            - ``total`` (*int*) — total number of entities.
            - ``by_datatype`` (:class:`~collections.Counter`) — counts per
              declared datatype (``None`` keys are preserved).
            - ``by_source_type`` (:class:`~collections.Counter`) — counts per
              ``source_type`` value.
            - ``missing_descriptions`` (*int*) — number of entities whose
              ``description`` field is ``None`` or empty.
        """
        by_datatype: Counter = Counter(e.datatype for e in entities)
        by_source_type: Counter = Counter(e.source_type for e in entities)
        missing_descriptions = sum(
            1 for e in entities if not e.description
        )

        summary = {
            "total": len(entities),
            "by_datatype": by_datatype,
            "by_source_type": by_source_type,
            "missing_descriptions": missing_descriptions,
        }
        logger.debug(
            "Source profile summary: total=%d, missing_descriptions=%d",
            summary["total"],
            summary["missing_descriptions"],
        )
        return summary

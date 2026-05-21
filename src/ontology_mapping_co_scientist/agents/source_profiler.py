"""Source profiler agent for the Ontology Mapping Co-Scientist system.

This module defines :class:`SourceProfilerAgent`, which is responsible for
loading and profiling source entities from supported input file formats.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from ontology_mapping_co_scientist.io.csv_loader import load_csv_entities
from ontology_mapping_co_scientist.io.openapi_loader import load_openapi_entities
from ontology_mapping_co_scientist.models.entities import SourceEntity

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

"""Tests for SourceProfilerAgent and the underlying CSV / OpenAPI loaders.

These tests exercise real file I/O and real parsing logic without mocking the
filesystem or the loaders.  Deterministic temporary files are provided via
conftest fixtures (``tmp_csv_file``, ``tmp_openapi_json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontology_mapping_co_scientist.agents.source_profiler import SourceProfilerAgent
from ontology_mapping_co_scientist.io.csv_loader import load_csv_entities
from ontology_mapping_co_scientist.io.openapi_loader import load_openapi_entities
from ontology_mapping_co_scientist.models.entities import SourceEntity


class TestSourceProfilerAgent:
    """Tests for the high-level SourceProfilerAgent interface."""

    # ------------------------------------------------------------------
    # CSV profiling
    # ------------------------------------------------------------------

    def test_profile_csv_returns_source_entities(self, tmp_csv_file: Path) -> None:
        """profile_csv should return a non-empty list of SourceEntity objects."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)

        assert isinstance(entities, list), "Return value must be a list"
        assert len(entities) > 0, "Must return at least one entity"
        for entity in entities:
            assert isinstance(entity, SourceEntity), (
                f"Every item must be a SourceEntity, got {type(entity)}"
            )

    def test_profile_csv_entity_ids_start_with_csv_prefix(
        self, tmp_csv_file: Path
    ) -> None:
        """All entity_ids from a CSV file must start with the 'csv:' prefix."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)

        for entity in entities:
            assert entity.entity_id.startswith("csv:"), (
                f"entity_id {entity.entity_id!r} does not start with 'csv:'"
            )

    def test_profile_csv_labels_match_column_names(self, tmp_csv_file: Path) -> None:
        """Entity labels must correspond to CSV column header names."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)

        labels = {e.label for e in entities}
        # The fixture CSV has columns: animal_id, strain, sex, age_weeks
        expected_labels = {"animal_id", "strain", "sex", "age_weeks"}
        assert expected_labels == labels, (
            f"Expected labels {expected_labels}, got {labels}"
        )

    def test_profile_csv_datatype_inference(self, tmp_csv_file: Path) -> None:
        """The 'age_weeks' column (all integers) must be inferred as datatype 'number'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)

        age_entity = next(
            (e for e in entities if e.label == "age_weeks"), None
        )
        assert age_entity is not None, "Expected an entity with label 'age_weeks'"
        assert age_entity.datatype == "number", (
            f"Expected datatype='number' for age_weeks, got {age_entity.datatype!r}"
        )

    def test_profile_csv_string_columns_get_string_datatype(
        self, tmp_csv_file: Path
    ) -> None:
        """Columns with mixed text values (e.g. 'strain') must get datatype 'string'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)

        strain_entity = next(
            (e for e in entities if e.label == "strain"), None
        )
        assert strain_entity is not None, "Expected an entity with label 'strain'"
        assert strain_entity.datatype == "string", (
            f"Expected datatype='string' for strain, got {strain_entity.datatype!r}"
        )

    # ------------------------------------------------------------------
    # OpenAPI profiling
    # ------------------------------------------------------------------

    def test_profile_openapi_returns_entities(self, tmp_openapi_json: Path) -> None:
        """profile_openapi should return a non-empty list of SourceEntity objects."""
        agent = SourceProfilerAgent()
        entities = agent.profile_openapi(tmp_openapi_json)

        assert isinstance(entities, list), "Return value must be a list"
        assert len(entities) > 0, "Must return at least one entity"
        for entity in entities:
            assert isinstance(entity, SourceEntity), (
                f"Every item must be a SourceEntity, got {type(entity)}"
            )

    def test_profile_openapi_entities_have_openapi_source_type(
        self, tmp_openapi_json: Path
    ) -> None:
        """All entities from an OpenAPI file must have source_type='openapi'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_openapi(tmp_openapi_json)

        for entity in entities:
            assert entity.source_type == "openapi", (
                f"Expected source_type='openapi', got {entity.source_type!r}"
            )

    def test_profile_openapi_entity_ids_start_with_api_prefix(
        self, tmp_openapi_json: Path
    ) -> None:
        """OpenAPI entity_ids must use the 'api:' prefix."""
        agent = SourceProfilerAgent()
        entities = agent.profile_openapi(tmp_openapi_json)

        for entity in entities:
            assert entity.entity_id.startswith("api:"), (
                f"entity_id {entity.entity_id!r} does not start with 'api:'"
            )

    # ------------------------------------------------------------------
    # Auto-detection
    # ------------------------------------------------------------------

    def test_profile_auto_csv(self, tmp_csv_file: Path) -> None:
        """profile_auto should detect .csv extension and delegate to profile_csv."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(tmp_csv_file)

        assert len(entities) > 0, "Must return at least one entity"
        assert all(e.source_type == "csv" for e in entities), (
            "Auto-detected CSV file must produce entities with source_type='csv'"
        )

    def test_profile_auto_json(self, tmp_openapi_json: Path) -> None:
        """profile_auto should detect .json extension and delegate to profile_openapi."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(tmp_openapi_json)

        assert len(entities) > 0, "Must return at least one entity"
        assert all(e.source_type == "openapi" for e in entities), (
            "Auto-detected JSON file must produce entities with source_type='openapi'"
        )

    def test_profile_auto_unknown_extension_raises_value_error(
        self, tmp_path: Path
    ) -> None:
        """profile_auto must raise ValueError for unsupported file extensions."""
        unknown_file = tmp_path / "schema.yaml"
        unknown_file.write_text("field: value\n", encoding="utf-8")

        agent = SourceProfilerAgent()
        with pytest.raises(ValueError, match="Unsupported file extension"):
            agent.profile_auto(unknown_file)

    # ------------------------------------------------------------------
    # Summarize
    # ------------------------------------------------------------------

    def test_summarize_returns_dict_with_total_key(
        self, tmp_csv_file: Path
    ) -> None:
        """summarize must return a dict containing at least the 'total' key."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)
        summary = agent.summarize(entities)

        assert isinstance(summary, dict), "summarize must return a dict"
        assert "total" in summary, "summary dict must contain 'total' key"

    def test_summarize_total_matches_entity_count(
        self, tmp_csv_file: Path
    ) -> None:
        """summary['total'] must equal the number of entities returned by profiling."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)
        summary = agent.summarize(entities)

        assert summary["total"] == len(entities), (
            f"summary['total']={summary['total']} does not match "
            f"len(entities)={len(entities)}"
        )

    def test_summarize_contains_by_datatype(self, tmp_csv_file: Path) -> None:
        """summary must contain a 'by_datatype' entry with per-datatype counts."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)
        summary = agent.summarize(entities)

        assert "by_datatype" in summary, "summary must contain 'by_datatype'"
        # 'number' datatype should appear at least once (age_weeks column)
        assert summary["by_datatype"]["number"] >= 1, (
            "Expected at least one 'number' datatype entity (age_weeks)"
        )

    def test_summarize_contains_missing_descriptions(
        self, tmp_csv_file: Path
    ) -> None:
        """summary must contain 'missing_descriptions' with a non-negative count."""
        agent = SourceProfilerAgent()
        entities = agent.profile_csv(tmp_csv_file)
        summary = agent.summarize(entities)

        assert "missing_descriptions" in summary, (
            "summary must contain 'missing_descriptions'"
        )
        assert isinstance(summary["missing_descriptions"], int), (
            "'missing_descriptions' must be an int"
        )
        assert summary["missing_descriptions"] >= 0


# ---------------------------------------------------------------------------
# Direct loader tests
# ---------------------------------------------------------------------------


class TestCsvLoader:
    """Unit tests for load_csv_entities directly."""

    def test_csv_loader_basic(self, tmp_csv_file: Path) -> None:
        """load_csv_entities must return one SourceEntity per non-description column."""
        entities = load_csv_entities(tmp_csv_file)

        # Fixture has 4 columns (animal_id, strain, sex, age_weeks)
        assert len(entities) == 4, (
            f"Expected 4 entities (one per column), got {len(entities)}"
        )

    def test_csv_loader_source_type(self, tmp_csv_file: Path) -> None:
        """load_csv_entities must set source_type='csv' on all returned entities."""
        entities = load_csv_entities(tmp_csv_file)
        for entity in entities:
            assert entity.source_type == "csv"

    def test_csv_loader_entity_id_format(self, tmp_csv_file: Path) -> None:
        """entity_id must follow the 'csv:<stem>.<column>' convention."""
        entities = load_csv_entities(tmp_csv_file)
        stem = tmp_csv_file.stem  # 'animals'
        for entity in entities:
            assert entity.entity_id.startswith(f"csv:{stem}."), (
                f"entity_id {entity.entity_id!r} does not follow expected format"
            )

    def test_csv_loader_examples_populated(self, tmp_csv_file: Path) -> None:
        """load_csv_entities must collect up to three example values per column."""
        entities = load_csv_entities(tmp_csv_file)
        # Every entity should have at least one example from the 3-row fixture
        for entity in entities:
            assert len(entity.examples) >= 1, (
                f"Entity {entity.entity_id} has no examples"
            )
            assert len(entity.examples) <= 3, (
                f"Entity {entity.entity_id} has more than 3 examples"
            )

    def test_csv_loader_missing_file_raises(self, tmp_path: Path) -> None:
        """load_csv_entities must raise FileNotFoundError for a missing file."""
        missing = tmp_path / "nonexistent.csv"
        with pytest.raises(FileNotFoundError):
            load_csv_entities(missing)

    def test_csv_loader_number_datatype_inferred(self, tmp_csv_file: Path) -> None:
        """Numeric columns must get datatype='number'."""
        entities = load_csv_entities(tmp_csv_file)
        age_entity = next((e for e in entities if e.label == "age_weeks"), None)
        assert age_entity is not None
        assert age_entity.datatype == "number"


class TestOpenApiLoader:
    """Unit tests for load_openapi_entities directly."""

    def test_openapi_loader_basic(self, tmp_openapi_json: Path) -> None:
        """load_openapi_entities must return one entity per schema property."""
        entities = load_openapi_entities(tmp_openapi_json)

        # Fixture has Animal schema with 3 properties
        assert len(entities) == 3, (
            f"Expected 3 entities (Animal.animal_id, .strain, .age_weeks), "
            f"got {len(entities)}"
        )

    def test_openapi_loader_source_type(self, tmp_openapi_json: Path) -> None:
        """load_openapi_entities must set source_type='openapi' on all entities."""
        entities = load_openapi_entities(tmp_openapi_json)
        for entity in entities:
            assert entity.source_type == "openapi", (
                f"Expected source_type='openapi', got {entity.source_type!r}"
            )

    def test_openapi_loader_extracts_descriptions(
        self, tmp_openapi_json: Path
    ) -> None:
        """Entities whose properties carry a 'description' field must have it populated."""
        entities = load_openapi_entities(tmp_openapi_json)
        strain_entity = next((e for e in entities if e.label == "strain"), None)
        assert strain_entity is not None, "Expected an entity with label 'strain'"
        assert strain_entity.description is not None, (
            "'strain' property has a description in the fixture — it must be loaded"
        )
        assert len(strain_entity.description) > 0

    def test_openapi_loader_entity_id_format(self, tmp_openapi_json: Path) -> None:
        """entity_ids must follow the 'api:<schema>.<property>' pattern."""
        entities = load_openapi_entities(tmp_openapi_json)
        for entity in entities:
            assert entity.entity_id.startswith("api:Animal."), (
                f"entity_id {entity.entity_id!r} does not follow 'api:Animal.*' format"
            )

    def test_openapi_loader_extracts_examples(self, tmp_openapi_json: Path) -> None:
        """Properties with an 'example' field must have at least one example value."""
        entities = load_openapi_entities(tmp_openapi_json)
        strain_entity = next((e for e in entities if e.label == "strain"), None)
        assert strain_entity is not None
        assert len(strain_entity.examples) >= 1, (
            "strain property has an example in the fixture — it must be extracted"
        )

    def test_openapi_loader_missing_file_raises(self, tmp_path: Path) -> None:
        """load_openapi_entities must raise FileNotFoundError for a missing file."""
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError):
            load_openapi_entities(missing)

    def test_openapi_loader_invalid_json_raises(self, tmp_path: Path) -> None:
        """load_openapi_entities must raise ValueError for malformed JSON input."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{ not valid json }", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot parse JSON"):
            load_openapi_entities(bad_json)

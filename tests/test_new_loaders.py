"""Tests for the JSON Schema and RDF/OWL loaders, and their wiring into the
profiler agents.

Requires PYTHONPATH=src to be set when running with pytest directly.
The conftest.py already inserts src/ into sys.path.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ontology_mapping_co_scientist.agents.source_profiler import SourceProfilerAgent
from ontology_mapping_co_scientist.io.json_schema_loader import load_json_schema_entities
from ontology_mapping_co_scientist.models.entities import SourceEntity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BIOBANK_SCHEMA = (
    Path(__file__).parent.parent
    / "examples"
    / "source_jsonschema"
    / "biobank_sample_schema.json"
)


# ---------------------------------------------------------------------------
# Task F1: JSON Schema loader tests
# ---------------------------------------------------------------------------


class TestJsonSchemaLoaderBasic:
    """test_json_schema_loader_basic — core functionality."""

    def test_returns_list_of_source_entities(self) -> None:
        """load_json_schema_entities must return a list of SourceEntity objects."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        assert isinstance(entities, list), "Return value must be a list"
        assert len(entities) > 0, "Must return at least one entity"
        for entity in entities:
            assert isinstance(entity, SourceEntity), (
                f"Every item must be a SourceEntity, got {type(entity)}"
            )

    def test_entity_ids_start_with_jschema_prefix(self) -> None:
        """All entity_ids must start with the 'jschema:' prefix."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.entity_id.startswith("jschema:"), (
                f"entity_id {entity.entity_id!r} does not start with 'jschema:'"
            )

    def test_at_least_ten_entities(self) -> None:
        """The biobank schema must yield at least 10 entities."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        assert len(entities) >= 10, (
            f"Expected at least 10 entities, got {len(entities)}"
        )

    def test_source_type_is_json_schema(self) -> None:
        """All entities must have source_type='json_schema'."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.source_type == "json_schema", (
                f"Expected source_type='json_schema', got {entity.source_type!r}"
            )

    def test_sorted_by_entity_id(self) -> None:
        """Return value must be sorted by entity_id."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        ids = [e.entity_id for e in entities]
        assert ids == sorted(ids), "Entities must be sorted by entity_id"

    def test_deduplicated_entity_ids(self) -> None:
        """No two entities should share the same entity_id."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        ids = [e.entity_id for e in entities]
        assert len(ids) == len(set(ids)), "entity_ids must be unique (no duplicates)"

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        """FileNotFoundError must be raised for a missing file."""
        with pytest.raises(FileNotFoundError):
            load_json_schema_entities(tmp_path / "nonexistent.json")

    def test_invalid_json_raises_value_error(self, tmp_path: Path) -> None:
        """ValueError must be raised for malformed JSON."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json}", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot parse JSON"):
            load_json_schema_entities(bad)


class TestJsonSchemaLoaderDatatypeInference:
    """test_json_schema_loader_datatype_inference."""

    def test_numeric_fields_get_number_datatype(self) -> None:
        """Fields with JSON Schema type 'number' or 'integer' must get datatype='number'."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        # Fields we know are numeric in the biobank schema
        numeric_labels = {
            "age", "volume_ml", "concentration_ug_ul", "purity_ratio_260_280",
            "integrity_number_rin", "storage_temperature_c", "volume_ul",
            "freeze_thaw_cycles",
        }
        numeric_entities = [e for e in entities if e.label in numeric_labels]
        assert len(numeric_entities) > 0, "Expected some numeric entities to be present"
        for entity in numeric_entities:
            assert entity.datatype == "number", (
                f"Expected datatype='number' for '{entity.label}' "
                f"(id={entity.entity_id!r}), got {entity.datatype!r}"
            )

    def test_string_fields_get_string_datatype(self) -> None:
        """Fields with JSON Schema type 'string' must get datatype='string'."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        string_labels = {"tissue_type", "diagnosis_code", "storage_location", "ethnicity"}
        string_entities = [e for e in entities if e.label in string_labels]
        assert len(string_entities) > 0, "Expected some string entities to be present"
        for entity in string_entities:
            assert entity.datatype == "string", (
                f"Expected datatype='string' for '{entity.label}', "
                f"got {entity.datatype!r}"
            )

    def test_array_field_gets_array_datatype(self, tmp_path: Path) -> None:
        """Fields with JSON Schema type 'array' must get datatype='array'."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "TestSchema",
            "type": "object",
            "properties": {
                "tags": {"type": "array", "description": "A list of tags."}
            },
        }
        schema_path = tmp_path / "test.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)
        tags_entity = next((e for e in entities if e.label == "tags"), None)
        assert tags_entity is not None
        assert tags_entity.datatype == "array"

    def test_boolean_field_gets_boolean_datatype(self, tmp_path: Path) -> None:
        """Fields with JSON Schema type 'boolean' must get datatype='boolean'."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "TestSchema",
            "type": "object",
            "properties": {
                "active": {"type": "boolean", "description": "Whether record is active."}
            },
        }
        schema_path = tmp_path / "test.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)
        active_entity = next((e for e in entities if e.label == "active"), None)
        assert active_entity is not None
        assert active_entity.datatype == "boolean"

    def test_unknown_type_field_gets_unknown_datatype(self, tmp_path: Path) -> None:
        """Fields with no 'type' key must get datatype='unknown'."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "TestSchema",
            "type": "object",
            "properties": {
                "notes": {"description": "Free-form notes with no declared type."}
            },
        }
        schema_path = tmp_path / "test.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)
        notes_entity = next((e for e in entities if e.label == "notes"), None)
        assert notes_entity is not None
        assert notes_entity.datatype == "unknown"


class TestJsonSchemaLoaderNested:
    """test_json_schema_loader_nested — dot notation for nested objects."""

    def test_nested_properties_use_dot_notation(self) -> None:
        """Nested object properties must have dot-separated paths in entity_id."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        # The schema has definitions like Donor.age, Sample.volume_ml, etc.
        nested = [e for e in entities if e.entity_id.count(".") >= 2]
        assert len(nested) > 0, (
            "Expected nested entities with dot notation paths (e.g. 'Donor.age')"
        )

    def test_nested_entity_id_format(self, tmp_path: Path) -> None:
        """Nested object entity_ids must follow 'jschema:<schema>.<parent>.<child>' pattern."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Animal",
            "type": "object",
            "properties": {
                "measurements": {
                    "type": "object",
                    "description": "Physical measurements.",
                    "properties": {
                        "weight": {
                            "type": "number",
                            "description": "Body weight in kg.",
                        }
                    },
                }
            },
        }
        schema_path = tmp_path / "animal.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)
        weight_entity = next((e for e in entities if e.label == "weight"), None)
        assert weight_entity is not None, "Expected 'weight' entity from nested object"
        assert weight_entity.entity_id == "jschema:Animal.measurements.weight", (
            f"Unexpected entity_id: {weight_entity.entity_id!r}"
        )

    def test_definitions_are_extracted(self) -> None:
        """Properties inside 'definitions' must be extracted as entities."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        # Donor, Sample, Aliquot are in definitions
        donor_ids = [e for e in entities if "Donor." in e.entity_id]
        assert len(donor_ids) > 0, "Expected entities from 'definitions/Donor'"

    def test_extra_context_contains_depth(self) -> None:
        """extra_context must include a 'depth' key for all entities."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        for entity in entities:
            assert "depth" in entity.extra_context, (
                f"Entity {entity.entity_id!r} missing 'depth' in extra_context"
            )

    def test_extra_context_contains_parent_schema(self) -> None:
        """extra_context must include a 'parent_schema' key."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        for entity in entities:
            assert "parent_schema" in entity.extra_context, (
                f"Entity {entity.entity_id!r} missing 'parent_schema' in extra_context"
            )

    def test_max_depth_limits_recursion(self, tmp_path: Path) -> None:
        """Setting max_depth=0 must prevent extraction of nested properties."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "DeepSchema",
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "inner": {"type": "string", "description": "Deep field."}
                    },
                }
            },
        }
        schema_path = tmp_path / "deep.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities_depth0 = load_json_schema_entities(schema_path, max_depth=0)
        inner_0 = [e for e in entities_depth0 if e.label == "inner"]
        assert len(inner_0) == 0, "max_depth=0 must prevent nested property extraction"

        entities_depth2 = load_json_schema_entities(schema_path, max_depth=2)
        inner_2 = [e for e in entities_depth2 if e.label == "inner"]
        assert len(inner_2) > 0, "max_depth=2 must allow nested property extraction"


class TestJsonSchemaLoaderRefResolution:
    """test_json_schema_loader_ref_resolution — $ref handling."""

    def test_ref_properties_are_resolved(self) -> None:
        """Properties from $ref-referenced schemas must be extracted."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        # The root schema has "donor": {"$ref": "#/definitions/Donor"}
        # After resolution, nested Donor properties should appear under "donor.*"
        donor_nested = [
            e for e in entities if e.entity_id.startswith("jschema:BiobankSample.donor.")
        ]
        assert len(donor_nested) > 0, (
            "Expected entities from $ref-resolved 'donor' property "
            f"(e.g. 'jschema:BiobankSample.donor.age'). Got ids: "
            f"{[e.entity_id for e in entities[:10]]}"
        )

    def test_defs_ref_resolution(self, tmp_path: Path) -> None:
        """$ref pointing to #/$defs/Foo must resolve to the correct sub-schema."""
        schema = {
            "$schema": "http://json-schema.org/draft-2019-09/schema",
            "title": "MySchema",
            "type": "object",
            "properties": {
                "address": {"$ref": "#/$defs/Address"}
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "properties": {
                        "street": {"type": "string", "description": "Street name."},
                        "city": {"type": "string", "description": "City name."},
                        "postcode": {"type": "string", "description": "Postal code."},
                    },
                }
            },
        }
        schema_path = tmp_path / "myschema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)

        # $defs/Address properties should be in entities (extracted from $defs)
        address_labels = {e.label for e in entities}
        assert "street" in address_labels, (
            "'street' from $defs/Address must be extracted as a SourceEntity"
        )
        assert "city" in address_labels
        assert "postcode" in address_labels

    def test_definitions_ref_resolution(self, tmp_path: Path) -> None:
        """$ref pointing to #/definitions/Foo must resolve correctly."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "RefTest",
            "type": "object",
            "properties": {
                "person": {"$ref": "#/definitions/Person"}
            },
            "definitions": {
                "Person": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Full name."},
                        "dob": {"type": "string", "format": "date", "description": "Date of birth."},
                    },
                }
            },
        }
        schema_path = tmp_path / "reftest.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        entities = load_json_schema_entities(schema_path)

        labels = {e.label for e in entities}
        assert "name" in labels, "Expected 'name' from $ref-resolved Person definition"
        assert "dob" in labels, "Expected 'dob' from $ref-resolved Person definition"

    def test_enum_in_extra_context(self) -> None:
        """Properties with 'enum' must have their enum values in extra_context."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        sex_entities = [e for e in entities if e.label == "sex"]
        assert len(sex_entities) > 0, "Expected at least one 'sex' entity"
        sex_entity = sex_entities[0]
        assert sex_entity.extra_context.get("enum") is not None, (
            "'sex' property has an enum — must appear in extra_context['enum']"
        )

    def test_default_value_included_in_examples(self) -> None:
        """Properties with a 'default' key must include the default value in examples."""
        entities = load_json_schema_entities(_BIOBANK_SCHEMA)
        # storage_temperature_c has default: -80
        temp_entities = [
            e for e in entities if e.label == "storage_temperature_c"
        ]
        assert len(temp_entities) > 0, "Expected at least one 'storage_temperature_c' entity"
        # At least one should have the default in examples
        found_default = any(
            "-80" in e.examples for e in temp_entities
        )
        assert found_default, (
            "Expected default value '-80' in examples of 'storage_temperature_c'"
        )


# ---------------------------------------------------------------------------
# Task F2: RDF loader — import error if no rdflib
# ---------------------------------------------------------------------------


class TestRdfLoaderImportError:
    """test_rdf_loader_import_error_if_no_rdflib."""

    def test_import_error_raised_when_rdflib_unavailable(
        self, tmp_path: Path
    ) -> None:
        """When rdflib is not installed, load_rdf_ontology must raise ImportError."""
        # We patch HAS_RDFLIB to False to simulate missing rdflib
        import ontology_mapping_co_scientist.io.rdf_ontology_loader as rdf_mod

        original_has_rdflib = rdf_mod.HAS_RDFLIB
        try:
            rdf_mod.HAS_RDFLIB = False
            with pytest.raises(ImportError, match="rdflib is required"):
                rdf_mod.load_rdf_ontology(tmp_path / "dummy.owl")
        finally:
            rdf_mod.HAS_RDFLIB = original_has_rdflib

    def test_detect_ontology_format_turtle(self, tmp_path: Path) -> None:
        """detect_ontology_format must return 'turtle' for .ttl files."""
        from ontology_mapping_co_scientist.io.rdf_ontology_loader import detect_ontology_format

        ttl_file = tmp_path / "onto.ttl"
        ttl_file.write_text("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n")
        assert detect_ontology_format(ttl_file) == "turtle"

    def test_detect_ontology_format_xml(self, tmp_path: Path) -> None:
        """detect_ontology_format must return 'xml' for .owl files."""
        from ontology_mapping_co_scientist.io.rdf_ontology_loader import detect_ontology_format

        owl_file = tmp_path / "onto.owl"
        owl_file.write_text("<?xml version='1.0'?><rdf:RDF/>")
        assert detect_ontology_format(owl_file) == "xml"

    def test_detect_ontology_format_ntriples(self, tmp_path: Path) -> None:
        """detect_ontology_format must return 'ntriples' for .nt files."""
        from ontology_mapping_co_scientist.io.rdf_ontology_loader import detect_ontology_format

        nt_file = tmp_path / "onto.nt"
        nt_file.write_text("<http://ex.org/a> <http://ex.org/b> <http://ex.org/c> .\n")
        assert detect_ontology_format(nt_file) == "ntriples"

    def test_detect_ontology_format_jsonld(self, tmp_path: Path) -> None:
        """detect_ontology_format must return 'json-ld' for .jsonld files."""
        from ontology_mapping_co_scientist.io.rdf_ontology_loader import detect_ontology_format

        jld_file = tmp_path / "onto.jsonld"
        jld_file.write_text('{"@context": {}}')
        assert detect_ontology_format(jld_file) == "json-ld"


# ---------------------------------------------------------------------------
# Wiring tests: SourceProfilerAgent
# ---------------------------------------------------------------------------


class TestSourceProfilerAutoDetectsJsonSchema:
    """test_source_profiler_auto_detects_json_schema."""

    def test_profile_auto_uses_json_schema_loader_when_schema_key_present(
        self,
    ) -> None:
        """profile_auto must delegate to profile_json_schema for JSON Schema files."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(_BIOBANK_SCHEMA)

        assert len(entities) >= 10, (
            f"Expected at least 10 entities from biobank schema, got {len(entities)}"
        )
        for entity in entities:
            assert entity.source_type == "json_schema", (
                f"Expected source_type='json_schema', got {entity.source_type!r}"
            )

    def test_profile_auto_uses_openapi_loader_for_non_schema_json(
        self, tmp_openapi_json: Path
    ) -> None:
        """profile_auto must delegate to profile_openapi for JSON files without '$schema'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(tmp_openapi_json)

        assert len(entities) > 0
        for entity in entities:
            assert entity.source_type == "openapi", (
                f"Expected source_type='openapi' for OpenAPI file, got {entity.source_type!r}"
            )

    def test_profile_auto_json_schema_entity_ids_start_with_jschema(
        self,
    ) -> None:
        """Entities from a JSON Schema file via profile_auto must have 'jschema:' prefix."""
        agent = SourceProfilerAgent()
        entities = agent.profile_auto(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.entity_id.startswith("jschema:"), (
                f"entity_id {entity.entity_id!r} does not start with 'jschema:'"
            )


class TestSourceProfilerProfileJsonSchemaDirect:
    """test_source_profiler_profile_json_schema_direct."""

    def test_profile_json_schema_returns_source_entities(self) -> None:
        """profile_json_schema must return a non-empty list of SourceEntity objects."""
        agent = SourceProfilerAgent()
        entities = agent.profile_json_schema(_BIOBANK_SCHEMA)

        assert isinstance(entities, list), "Return value must be a list"
        assert len(entities) > 0
        for entity in entities:
            assert isinstance(entity, SourceEntity)

    def test_profile_json_schema_entity_ids_start_with_jschema(self) -> None:
        """All entity_ids from profile_json_schema must start with 'jschema:'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_json_schema(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.entity_id.startswith("jschema:")

    def test_profile_json_schema_source_type(self) -> None:
        """All entities must have source_type='json_schema'."""
        agent = SourceProfilerAgent()
        entities = agent.profile_json_schema(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.source_type == "json_schema"

    def test_profile_json_schema_missing_file_raises(self, tmp_path: Path) -> None:
        """profile_json_schema must propagate FileNotFoundError for missing files."""
        agent = SourceProfilerAgent()
        with pytest.raises(FileNotFoundError):
            agent.profile_json_schema(tmp_path / "nonexistent.json")

    def test_profile_json_schema_source_file_is_set(self) -> None:
        """All entities must have source_file set to the input file path."""
        agent = SourceProfilerAgent()
        entities = agent.profile_json_schema(_BIOBANK_SCHEMA)
        for entity in entities:
            assert entity.source_file is not None
            assert "biobank_sample_schema" in entity.source_file

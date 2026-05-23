"""Tests for mapping_co_scientist.schema_align.execution.transformation_executor."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from mapping_co_scientist.schema_align.models.transformation_rule import (
    MappingOperation,
    TransformationRule,
)
from mapping_co_scientist.schema_align.execution.transformation_executor import (
    ExecutionResult,
    TransformationExecutor,
    _set_nested,
)


# ---------------------------------------------------------------------------
# Helper to build rules quickly
# ---------------------------------------------------------------------------


def _rule(
    rule_id: str,
    operation: MappingOperation,
    source_path: str | None = None,
    target_path: str = "output",
    constant_value: Any = None,
    datatype_to: str | None = None,
    unit_conversion_factor: float | None = None,
    enumeration_map: dict | None = None,
) -> TransformationRule:
    kwargs: dict[str, Any] = {
        "rule_id": rule_id,
        "operation": operation,
        "source_path": source_path,
        "target_path": target_path,
        "constant_value": constant_value,
        "datatype_to": datatype_to,
        "unit_conversion_factor": unit_conversion_factor,
    }
    if enumeration_map is not None:
        kwargs["enumeration_map"] = enumeration_map
    return TransformationRule(**kwargs)


# ---------------------------------------------------------------------------
# _set_nested helper
# ---------------------------------------------------------------------------


def test_set_nested_simple_key() -> None:
    """_set_nested with a flat key sets the value directly."""
    target: dict = {}
    _set_nested(target, "name", "Alice")
    assert target == {"name": "Alice"}


def test_set_nested_creates_nested_dicts() -> None:
    """_set_nested with dot-notation creates intermediate dicts."""
    target: dict = {}
    _set_nested(target, "a.b.c", 42)
    assert target == {"a": {"b": {"c": 42}}}


# ---------------------------------------------------------------------------
# DIRECT_COPY
# ---------------------------------------------------------------------------


def test_direct_copy_copies_value() -> None:
    """DIRECT_COPY copies a source value to the target key unchanged."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.DIRECT_COPY, source_path="name", target_path="full_name")
    result = executor.execute({"name": "Bob"}, [rule])
    assert result.success is True
    assert result.target_record["full_name"] == "Bob"
    assert result.errors == []


# ---------------------------------------------------------------------------
# RENAME
# ---------------------------------------------------------------------------


def test_rename_copies_to_new_key() -> None:
    """RENAME copies source value to a different target key."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.RENAME, source_path="old_key", target_path="new_key")
    result = executor.execute({"old_key": "value"}, [rule])
    assert result.success is True
    assert result.target_record["new_key"] == "value"
    assert "old_key" not in result.target_record


# ---------------------------------------------------------------------------
# NESTED_PATH
# ---------------------------------------------------------------------------


def test_nested_path_creates_nested_dict_structure() -> None:
    """NESTED_PATH writes to a dot-notation path, creating intermediate dicts."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.NESTED_PATH, source_path="weight", target_path="body.mass.grams")
    result = executor.execute({"weight": 25.4}, [rule])
    assert result.success is True
    assert result.target_record == {"body": {"mass": {"grams": 25.4}}}


def test_nested_path_two_levels() -> None:
    """NESTED_PATH handles two-level dot-notation paths."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.NESTED_PATH, source_path="x", target_path="level1.level2")
    result = executor.execute({"x": 99}, [rule])
    assert result.target_record["level1"]["level2"] == 99


# ---------------------------------------------------------------------------
# CONSTANT_ASSIGNMENT
# ---------------------------------------------------------------------------


def test_constant_assignment_sets_literal_value() -> None:
    """CONSTANT_ASSIGNMENT sets a literal constant regardless of source record."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.CONSTANT_ASSIGNMENT, target_path="species", constant_value="Mus musculus")
    result = executor.execute({}, [rule])
    assert result.success is True
    assert result.target_record["species"] == "Mus musculus"


def test_constant_assignment_none_source_path_ok() -> None:
    """CONSTANT_ASSIGNMENT works when source_path is None (as expected)."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.CONSTANT_ASSIGNMENT, source_path=None, target_path="version", constant_value=2)
    result = executor.execute({"other": "ignored"}, [rule])
    assert result.target_record["version"] == 2


# ---------------------------------------------------------------------------
# DATATYPE_CONVERSION
# ---------------------------------------------------------------------------


def test_datatype_conversion_str_to_int() -> None:
    """DATATYPE_CONVERSION converts string '42' to integer 42."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.DATATYPE_CONVERSION,
        source_path="age",
        target_path="age_int",
        datatype_to="int",
    )
    result = executor.execute({"age": "42"}, [rule])
    assert result.success is True
    assert result.target_record["age_int"] == 42
    assert isinstance(result.target_record["age_int"], int)


def test_datatype_conversion_float_to_int_adds_precision_warning() -> None:
    """DATATYPE_CONVERSION float→int adds a warning when precision is lost."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.DATATYPE_CONVERSION,
        source_path="measurement",
        target_path="measurement_int",
        datatype_to="int",
    )
    result = executor.execute({"measurement": 3.7}, [rule])
    assert result.success is True
    assert result.target_record["measurement_int"] == 3
    assert any("precision" in w.lower() for w in result.warnings)


def test_datatype_conversion_int_to_str() -> None:
    """DATATYPE_CONVERSION converts integer to string."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.DATATYPE_CONVERSION,
        source_path="count",
        target_path="count_str",
        datatype_to="str",
    )
    result = executor.execute({"count": 5}, [rule])
    assert result.success is True
    assert result.target_record["count_str"] == "5"


def test_datatype_conversion_type_coercion_failure_adds_error() -> None:
    """DATATYPE_CONVERSION on an unconvertible value adds an error and success=False."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.DATATYPE_CONVERSION,
        source_path="label",
        target_path="label_int",
        datatype_to="int",
    )
    result = executor.execute({"label": "not_a_number"}, [rule])
    assert result.success is False
    assert len(result.errors) > 0
    assert any("coercion" in e.lower() or "r1" in e for e in result.errors)


# ---------------------------------------------------------------------------
# UNIT_CONVERSION
# ---------------------------------------------------------------------------


def test_unit_conversion_applies_factor_from_model_field() -> None:
    """UNIT_CONVERSION applies the unit_conversion_factor field on the rule."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.UNIT_CONVERSION,
        source_path="weight_kg",
        target_path="weight_g",
        unit_conversion_factor=1000.0,
    )
    result = executor.execute({"weight_kg": 0.5}, [rule])
    assert result.success is True
    assert abs(result.target_record["weight_g"] - 500.0) < 1e-9


def test_unit_conversion_no_factor_adds_warning() -> None:
    """UNIT_CONVERSION without a factor adds a warning and returns value unchanged."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.UNIT_CONVERSION,
        source_path="temp",
        target_path="temp_out",
    )
    result = executor.execute({"temp": 37.0}, [rule])
    # No factor — value returned unchanged with a warning
    assert result.success is True
    assert result.target_record["temp_out"] == 37.0
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# ENUMERATION_REMAPPING
# ---------------------------------------------------------------------------


def test_enumeration_remapping_maps_values() -> None:
    """ENUMERATION_REMAPPING maps source enum values to target values."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.ENUMERATION_REMAPPING,
        source_path="sex_code",
        target_path="sex_label",
        enumeration_map={"M": "male", "F": "female"},
    )
    result = executor.execute({"sex_code": "M"}, [rule])
    assert result.success is True
    assert result.target_record["sex_label"] == "male"


def test_enumeration_remapping_missing_value_adds_error() -> None:
    """ENUMERATION_REMAPPING adds an error when source value is not in the map."""
    executor = TransformationExecutor()
    rule = TransformationRule(
        rule_id="r1",
        operation=MappingOperation.ENUMERATION_REMAPPING,
        source_path="status",
        target_path="status_out",
        enumeration_map={"active": "ACTIVE"},
    )
    result = executor.execute({"status": "unknown_value"}, [rule])
    assert result.success is False
    assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Missing source key
# ---------------------------------------------------------------------------


def test_missing_source_key_adds_error() -> None:
    """When source_path is absent from source_record, an error is appended."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.DIRECT_COPY, source_path="nonexistent", target_path="out")
    result = executor.execute({}, [rule])
    assert result.success is False
    assert len(result.errors) > 0
    assert any("nonexistent" in e for e in result.errors)


# ---------------------------------------------------------------------------
# UNMAPPED / HUMAN_REVIEW_REQUIRED
# ---------------------------------------------------------------------------


def test_unmapped_skipped_with_warning() -> None:
    """UNMAPPED operation is skipped and a warning is added."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.UNMAPPED, source_path="x", target_path="y")
    result = executor.execute({"x": 1}, [rule])
    assert result.success is True  # no errors
    assert "y" not in result.target_record
    assert len(result.warnings) > 0


def test_human_review_required_skipped_with_warning() -> None:
    """HUMAN_REVIEW_REQUIRED operation is skipped and a warning is added."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.HUMAN_REVIEW_REQUIRED, source_path="x", target_path="y")
    result = executor.execute({"x": 1}, [rule])
    assert result.success is True
    assert "y" not in result.target_record
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# execute_batch
# ---------------------------------------------------------------------------


def test_execute_batch_processes_multiple_records() -> None:
    """execute_batch applies rules to each source record independently."""
    executor = TransformationExecutor()
    rule = _rule("r1", MappingOperation.DIRECT_COPY, source_path="name", target_path="full_name")
    records = [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}]
    results = executor.execute_batch(records, [rule])
    assert len(results) == 3
    assert results[0].target_record["full_name"] == "Alice"
    assert results[1].target_record["full_name"] == "Bob"
    assert results[2].target_record["full_name"] == "Carol"
    assert all(r.success for r in results)


# ---------------------------------------------------------------------------
# validate_against_schema
# ---------------------------------------------------------------------------


def test_validate_against_schema_catches_missing_required_field() -> None:
    """validate_against_schema reports an error for a missing required field."""
    executor = TransformationExecutor()
    schema = {
        "type": "object",
        "required": ["animal_id", "species"],
        "properties": {
            "animal_id": {"type": "string"},
            "species": {"type": "string"},
        },
    }
    result = ExecutionResult(success=True, target_record={"animal_id": "A001"})
    errors = executor.validate_against_schema(result, schema)
    assert any("species" in e for e in errors)
    assert not any("animal_id" in e for e in errors)


def test_validate_against_schema_catches_type_mismatch() -> None:
    """validate_against_schema reports an error when a field has the wrong type."""
    executor = TransformationExecutor()
    schema = {
        "type": "object",
        "properties": {
            "age": {"type": "integer"},
            "name": {"type": "string"},
        },
    }
    # 'age' is a string but schema expects integer
    result = ExecutionResult(success=True, target_record={"age": "twenty", "name": "Bob"})
    errors = executor.validate_against_schema(result, schema)
    assert any("age" in e for e in errors)
    assert not any("name" in e for e in errors)


def test_validate_against_schema_no_errors_when_valid() -> None:
    """validate_against_schema returns empty list when record matches schema."""
    executor = TransformationExecutor()
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "count": {"type": "integer"},
        },
    }
    result = ExecutionResult(success=True, target_record={"id": "X001", "count": 5})
    errors = executor.validate_against_schema(result, schema)
    assert errors == []


# ---------------------------------------------------------------------------
# End-to-end: all rule types combined
# ---------------------------------------------------------------------------


def test_end_to_end_all_rule_types() -> None:
    """All rule types exercised in a single execute() call produce correct output."""
    executor = TransformationExecutor()

    rules = [
        TransformationRule(
            rule_id="r_copy",
            operation=MappingOperation.DIRECT_COPY,
            source_path="animal_id",
            target_path="id",
        ),
        TransformationRule(
            rule_id="r_rename",
            operation=MappingOperation.RENAME,
            source_path="strain",
            target_path="genetic_background",
        ),
        TransformationRule(
            rule_id="r_nested",
            operation=MappingOperation.NESTED_PATH,
            source_path="weight_kg",
            target_path="measurements.weight.kg",
        ),
        TransformationRule(
            rule_id="r_const",
            operation=MappingOperation.CONSTANT_ASSIGNMENT,
            target_path="species",
            constant_value="Mus musculus",
        ),
        TransformationRule(
            rule_id="r_dtype",
            operation=MappingOperation.DATATYPE_CONVERSION,
            source_path="age_str",
            target_path="age_weeks",
            datatype_to="int",
        ),
        TransformationRule(
            rule_id="r_unit",
            operation=MappingOperation.UNIT_CONVERSION,
            source_path="weight_kg",
            target_path="weight_g",
            unit_conversion_factor=1000.0,
        ),
        TransformationRule(
            rule_id="r_enum",
            operation=MappingOperation.ENUMERATION_REMAPPING,
            source_path="sex_code",
            target_path="sex_label",
            enumeration_map={"M": "male", "F": "female"},
        ),
    ]

    source = {
        "animal_id": "A001",
        "strain": "C57BL/6J",
        "weight_kg": 0.025,
        "age_str": "8",
        "sex_code": "F",
    }

    result = executor.execute(source, rules)

    assert result.success is True
    assert result.target_record["id"] == "A001"
    assert result.target_record["genetic_background"] == "C57BL/6J"
    assert result.target_record["measurements"]["weight"]["kg"] == 0.025
    assert result.target_record["species"] == "Mus musculus"
    assert result.target_record["age_weeks"] == 8
    assert abs(result.target_record["weight_g"] - 25.0) < 1e-9
    assert result.target_record["sex_label"] == "female"

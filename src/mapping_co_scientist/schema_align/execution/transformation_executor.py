from __future__ import annotations
from typing import Any
from pydantic import BaseModel

from mapping_co_scientist.schema_align.models.transformation_rule import (
    TransformationRule,
    MappingOperation,
)


class ExecutionResult(BaseModel):
    success: bool
    target_record: dict[str, Any]
    errors: list[str] = []
    warnings: list[str] = []
    model_config = {"frozen": True}


def _set_nested(target: dict, path: str, value: Any) -> None:
    """Set a value in a nested dict using dot-notation path, creating intermediate dicts."""
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


class TransformationExecutor:
    """Executes a list of TransformationRule objects against a source record."""

    def execute(
        self,
        source_record: dict[str, Any],
        rules: list[TransformationRule],
    ) -> ExecutionResult:
        target: dict[str, Any] = {}
        errors: list[str] = []
        warnings: list[str] = []

        for rule in rules:
            op = rule.operation

            # Skip operations that require human attention
            if op in (MappingOperation.UNMAPPED, MappingOperation.HUMAN_REVIEW_REQUIRED):
                warnings.append(
                    f"Rule '{rule.rule_id}': operation '{op}' skipped — requires human review."
                )
                continue

            if op == MappingOperation.CONSTANT_ASSIGNMENT:
                # Use constant_value field first, fall back to parameters
                value = rule.constant_value
                if value is None:
                    params = getattr(rule, "parameters", {}) or {}
                    value = params.get("constant_value")
                _set_nested(target, rule.target_path, value)
                continue

            # All other operations require a source path and source value
            source_path = rule.source_path
            if source_path is None:
                errors.append(
                    f"Rule '{rule.rule_id}': source_path is None for operation '{op}'."
                )
                continue

            if source_path not in source_record:
                errors.append(
                    f"Rule '{rule.rule_id}': source key '{source_path}' not found in source record."
                )
                continue

            source_value = source_record[source_path]

            if op in (MappingOperation.DIRECT_COPY, MappingOperation.RENAME):
                _set_nested(target, rule.target_path, source_value)

            elif op == MappingOperation.NESTED_PATH:
                _set_nested(target, rule.target_path, source_value)

            elif op == MappingOperation.DATATYPE_CONVERSION:
                converted, conv_errors, conv_warnings = _do_datatype_conversion(
                    rule, source_value
                )
                if conv_errors:
                    errors.extend(conv_errors)
                else:
                    warnings.extend(conv_warnings)
                    _set_nested(target, rule.target_path, converted)

            elif op == MappingOperation.UNIT_CONVERSION:
                converted, conv_warnings = _do_unit_conversion(rule, source_value)
                warnings.extend(conv_warnings)
                _set_nested(target, rule.target_path, converted)

            elif op == MappingOperation.ENUMERATION_REMAPPING:
                enum_map = rule.enumeration_map or {}
                str_val = str(source_value)
                if str_val not in enum_map:
                    errors.append(
                        f"Rule '{rule.rule_id}': value '{str_val}' not found in enumeration map."
                    )
                else:
                    _set_nested(target, rule.target_path, enum_map[str_val])

            else:
                # Unsupported operation — skip with warning
                warnings.append(
                    f"Rule '{rule.rule_id}': operation '{op}' is not yet supported and was skipped."
                )

        return ExecutionResult(
            success=len(errors) == 0,
            target_record=target,
            errors=errors,
            warnings=warnings,
        )

    def execute_batch(
        self,
        source_records: list[dict[str, Any]],
        rules: list[TransformationRule],
    ) -> list[ExecutionResult]:
        return [self.execute(record, rules) for record in source_records]

    def validate_against_schema(
        self,
        result: ExecutionResult,
        target_schema: dict[str, Any],  # parsed JSON Schema dict
    ) -> list[str]:
        """Validate the target record against a JSON Schema dict.

        Checks required fields and basic type compatibility.
        Returns a list of error strings (empty means valid).
        """
        validation_errors: list[str] = []
        record = result.target_record
        properties = target_schema.get("properties", {})
        required = target_schema.get("required", [])

        # Check required fields
        for field_name in required:
            if field_name not in record:
                validation_errors.append(
                    f"Required field '{field_name}' is missing from target record."
                )

        # Check type compatibility for present fields
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for field_name, field_schema in properties.items():
            if field_name not in record:
                continue
            expected_type = field_schema.get("type")
            if expected_type is None:
                continue
            expected_python_type = type_map.get(expected_type)
            if expected_python_type is None:
                continue
            actual_value = record[field_name]
            # bool is a subclass of int in Python — check bool explicitly to avoid
            # falsely accepting True/False as integers when schema says "number"
            if expected_type in ("number", "integer") and isinstance(actual_value, bool):
                validation_errors.append(
                    f"Field '{field_name}': expected type '{expected_type}' but got bool."
                )
            elif not isinstance(actual_value, expected_python_type):
                actual_type_name = type(actual_value).__name__
                validation_errors.append(
                    f"Field '{field_name}': expected type '{expected_type}' "
                    f"but got '{actual_type_name}'."
                )

        return validation_errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_NUMERIC_TYPES = (int, float)


def _do_datatype_conversion(
    rule: TransformationRule, value: Any
) -> tuple[Any, list[str], list[str]]:
    """Attempt type coercion. Returns (converted_value, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    target_type = rule.datatype_to
    if target_type is None:
        # No conversion specified, return as-is
        return value, errors, warnings

    try:
        if target_type == "int" or target_type == "integer":
            if isinstance(value, float) and not value.is_integer():
                warnings.append(
                    f"Rule '{rule.rule_id}': precision lost converting float "
                    f"'{value}' to int."
                )
            converted = int(float(value)) if isinstance(value, str) else int(value)
        elif target_type == "float" or target_type == "number":
            converted = float(value)
        elif target_type == "str" or target_type == "string":
            converted = str(value)
        elif target_type == "bool" or target_type == "boolean":
            if isinstance(value, str):
                converted = value.lower() in ("true", "1", "yes")
            else:
                converted = bool(value)
        else:
            # Unknown target type — attempt a generic str conversion
            converted = str(value)
    except (ValueError, TypeError) as exc:
        errors.append(
            f"Rule '{rule.rule_id}': type coercion failed converting "
            f"'{value}' to '{target_type}': {exc}"
        )
        return None, errors, warnings

    return converted, errors, warnings


def _do_unit_conversion(
    rule: TransformationRule, value: Any
) -> tuple[Any, list[str]]:
    """Apply unit conversion factor. Returns (converted_value, warnings)."""
    warnings: list[str] = []

    # Prefer the dedicated model field, then fall back to parameters dict
    factor = rule.unit_conversion_factor
    if factor is None:
        params = getattr(rule, "parameters", {}) or {}
        factor = params.get("conversion_factor")

    if factor is None:
        warnings.append(
            f"Rule '{rule.rule_id}': no conversion_factor found; returning value unchanged."
        )
        return value, warnings

    try:
        converted = float(value) * float(factor)
    except (ValueError, TypeError) as exc:
        warnings.append(
            f"Rule '{rule.rule_id}': unit conversion failed for value '{value}': {exc}."
        )
        return value, warnings

    return converted, warnings

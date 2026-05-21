"""OpenAPI / Swagger schema loader for the Ontology Mapping Co-Scientist system.

Reads an OpenAPI 3.x (components/schemas) or Swagger 2.x (definitions) JSON
document and returns one :class:`SourceEntity` per schema property.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontology_mapping_co_scientist.models import SourceEntity


def _is_ref(value: Any) -> bool:
    """Return True if *value* is a JSON Schema ``$ref`` object."""
    return isinstance(value, dict) and "$ref" in value


def _extract_schemas(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract a flat ``{schema_name: schema_object}`` dict from the document.

    Supports:
    * OpenAPI 3.x: ``components -> schemas``
    * Swagger 2.x / OpenAPI 2.x: ``definitions``

    Args:
        doc: The parsed JSON document.

    Returns:
        A dict mapping schema names to their schema objects.
    """
    # OpenAPI 3.x
    components = doc.get("components", {})
    if isinstance(components, dict):
        schemas = components.get("schemas")
        if isinstance(schemas, dict):
            return schemas  # type: ignore[return-value]

    # Swagger 2.x
    definitions = doc.get("definitions")
    if isinstance(definitions, dict):
        return definitions  # type: ignore[return-value]

    return {}


def _resolve_required_set(schema_obj: dict[str, Any]) -> set[str]:
    """Return the set of required property names for a schema object."""
    required = schema_obj.get("required", [])
    return set(required) if isinstance(required, list) else set()


def load_openapi_entities(filepath: str | Path) -> list[SourceEntity]:
    """Load an OpenAPI / Swagger JSON file and return one :class:`SourceEntity` per property.

    For each schema found under ``components/schemas`` (OpenAPI 3.x) or
    ``definitions`` (Swagger 2.x), and for each property of that schema, one
    :class:`SourceEntity` is produced.

    Entity fields:
    * ``entity_id`` – ``"api:{schema_name}.{prop_name}"``
    * ``label`` – the property name as written in the schema
    * ``description`` – ``property.description`` if present, else ``None``
    * ``datatype`` – ``property.type`` if present, else ``"unknown"``
    * ``examples`` – ``[str(property["example"])]`` if an ``example`` key exists
    * ``source_file`` – absolute path string of the input file
    * ``source_type`` – ``"openapi"``
    * ``extra_context`` – dict containing:
      - ``schema_name`` (str)
      - ``required`` (bool) – whether the property is in the schema's required list
      - ``enum`` (list | None) – enum values if defined on the property
      - ``ref`` (str | None) – ``$ref`` value if the property is a reference
      - ``format`` (str | None) – JSON Schema format string if present
      - ``openapi_version`` (str) – ``"3.x"`` or ``"2.x"``

    Nested ``$ref`` objects are noted in ``extra_context["ref"]`` but are not
    recursively resolved.

    Args:
        filepath: Path to the OpenAPI JSON file (``str`` or :class:`pathlib.Path`).

    Returns:
        A list of :class:`SourceEntity` objects.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        ValueError: If the file cannot be parsed as JSON.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"OpenAPI file not found: {filepath}")

    try:
        with filepath.open(encoding="utf-8") as fh:
            doc: dict[str, Any] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse JSON file {filepath}: {exc}") from exc

    # Detect version
    openapi_version = "3.x" if "openapi" in doc else "2.x"

    schemas = _extract_schemas(doc)
    source_file = str(filepath)
    entities: list[SourceEntity] = []

    for schema_name, schema_obj in schemas.items():
        if not isinstance(schema_obj, dict):
            continue

        properties: dict[str, Any] = schema_obj.get("properties", {})
        if not isinstance(properties, dict):
            continue

        required_set = _resolve_required_set(schema_obj)

        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                continue

            # Detect $ref
            ref_value: str | None = None
            if _is_ref(prop_def):
                ref_value = prop_def["$ref"]
                description = None
                datatype = "unknown"
                examples: list[str] = []
                enum_values = None
                fmt = None
            else:
                description: str | None = prop_def.get("description")
                datatype: str = prop_def.get("type", "unknown")
                fmt: str | None = prop_def.get("format")
                enum_values: list[Any] | None = prop_def.get("enum")

                # Collect examples
                examples = []
                if "example" in prop_def:
                    examples = [str(prop_def["example"])]
                elif "examples" in prop_def and isinstance(prop_def["examples"], list):
                    examples = [str(e) for e in prop_def["examples"][:3]]

            extra_context: dict[str, Any] = {
                "schema_name": schema_name,
                "required": prop_name in required_set,
                "enum": enum_values,
                "ref": ref_value,
                "format": fmt,
                "openapi_version": openapi_version,
            }

            entity = SourceEntity(
                entity_id=f"api:{schema_name}.{prop_name}",
                label=prop_name,
                description=description,
                datatype=datatype,
                examples=examples,
                source_file=source_file,
                source_type="openapi",
                extra_context=extra_context,
            )
            entities.append(entity)

    return entities

"""
Loads JSON Schema files and extracts source entities from property definitions.
Supports draft-07, draft-2019-09, draft-2020-12. Recursively handles $defs,
definitions, allOf, anyOf, oneOf, and nested objects up to configurable depth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ontology_mapping_co_scientist.models.entities import SourceEntity

# ---------------------------------------------------------------------------
# JSON Schema type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def _map_type(json_type: Any) -> str:
    """Map a JSON Schema type value to a normalised datatype string.

    Args:
        json_type: The value of the ``type`` key in a JSON Schema property.

    Returns:
        One of ``"string"``, ``"number"``, ``"boolean"``, ``"array"``,
        ``"object"``, or ``"unknown"``.
    """
    if isinstance(json_type, list):
        # e.g. ["string", "null"] — use the first non-null type
        for t in json_type:
            if t != "null" and isinstance(t, str):
                return _TYPE_MAP.get(t, "unknown")
        return "unknown"
    if isinstance(json_type, str):
        return _TYPE_MAP.get(json_type, "unknown")
    return "unknown"


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def _resolve_ref(ref: str, schema_root: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local JSON Pointer ``$ref`` within the same document.

    Handles ``"#/$defs/Foo"`` and ``"#/definitions/Foo"`` style references.
    External (HTTP) references are returned as an empty dict.

    Args:
        ref: The ``$ref`` string value, e.g. ``"#/$defs/Donor"``.
        schema_root: The root JSON Schema document.

    Returns:
        The referenced sub-schema dict, or an empty dict if resolution fails.
    """
    if not ref.startswith("#"):
        # External reference — not supported
        return {}

    # Strip leading "#" and split on "/"
    pointer = ref.lstrip("#").lstrip("/")
    if not pointer:
        return schema_root

    parts = pointer.split("/")
    current: Any = schema_root
    for part in parts:
        # JSON Pointer escaping: ~1 -> /, ~0 -> ~
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return {}

    if isinstance(current, dict):
        return current
    return {}


# ---------------------------------------------------------------------------
# Property extraction helpers
# ---------------------------------------------------------------------------


def _collect_properties_from_schema(
    schema: dict[str, Any],
    schema_root: dict[str, Any],
) -> dict[str, Any]:
    """Collect a merged ``{name: property_def}`` dict from a schema object.

    Merges properties from: ``properties``, and all ``allOf``/``anyOf``/``oneOf``
    sub-schemas (recursively merged at one level).

    Args:
        schema: A JSON Schema sub-schema dict.
        schema_root: The root document (used for ``$ref`` resolution).

    Returns:
        A merged dict of property name → property definition.
    """
    merged: dict[str, Any] = {}

    # Direct properties
    direct = schema.get("properties", {})
    if isinstance(direct, dict):
        merged.update(direct)

    # Combiners: allOf, anyOf, oneOf
    for combiner in ("allOf", "anyOf", "oneOf"):
        sub_list = schema.get(combiner, [])
        if not isinstance(sub_list, list):
            continue
        for sub in sub_list:
            if not isinstance(sub, dict):
                continue
            # Resolve $ref if needed
            if "$ref" in sub:
                sub = _resolve_ref(sub["$ref"], schema_root)
            sub_props = sub.get("properties", {})
            if isinstance(sub_props, dict):
                merged.update(sub_props)

    return merged


def _extract_properties_recursive(
    schema: dict[str, Any],
    schema_root: dict[str, Any],
    schema_name: str,
    path_parts: list[str],
    required_set: set[str],
    parent_schema: str,
    depth: int,
    max_depth: int,
    source_file: str,
    seen_ids: set[str],
    results: list[SourceEntity],
) -> None:
    """Recursively extract properties from a schema object.

    Args:
        schema: The current schema object.
        schema_root: The root JSON Schema document.
        schema_name: The name of the top-level schema (used in entity_id).
        path_parts: The dot-notation path components accumulated so far.
        required_set: Set of required property names at *this* schema level.
        parent_schema: A label for the immediate parent schema (for extra_context).
        depth: Current recursion depth (0 = root level).
        max_depth: Maximum allowed recursion depth.
        source_file: Path string of the originating file.
        seen_ids: Set of entity_ids already emitted (for deduplication).
        results: Accumulator list to append SourceEntity objects to.
    """
    if depth > max_depth:
        return

    properties = _collect_properties_from_schema(schema, schema_root)

    for prop_name, prop_def in properties.items():
        if not isinstance(prop_def, dict):
            continue

        # Resolve $ref before further processing
        if "$ref" in prop_def:
            resolved = _resolve_ref(prop_def["$ref"], schema_root)
            if resolved:
                prop_def = {**resolved, **{k: v for k, v in prop_def.items() if k != "$ref"}}

        current_path = path_parts + [prop_name]
        property_path = ".".join(current_path)
        entity_id = f"jschema:{schema_name}.{property_path}"

        # Build SourceEntity fields
        description = prop_def.get("description") or prop_def.get("title")

        json_type = prop_def.get("type")
        datatype = _map_type(json_type)

        # Examples
        examples: list[str] = [str(e) for e in prop_def.get("examples", [])]
        if "default" in prop_def:
            examples.append(str(prop_def["default"]))

        # Extra context
        extra_context: dict[str, Any] = {
            "json_schema_type": json_type,
            "format": prop_def.get("format"),
            "enum": prop_def.get("enum"),
            "required": prop_name in required_set,
            "parent_schema": parent_schema,
            "depth": depth,
        }

        if entity_id not in seen_ids:
            seen_ids.add(entity_id)
            entity = SourceEntity(
                entity_id=entity_id,
                label=prop_name,
                description=description,
                datatype=datatype,
                examples=examples,
                source_file=source_file,
                source_type="json_schema",
                extra_context=extra_context,
            )
            results.append(entity)

        # Recurse into nested objects
        prop_type = prop_def.get("type")
        if prop_type == "object" and depth < max_depth:
            nested_required = set(prop_def.get("required", []))
            _extract_properties_recursive(
                schema=prop_def,
                schema_root=schema_root,
                schema_name=schema_name,
                path_parts=current_path,
                required_set=nested_required,
                parent_schema=property_path,
                depth=depth + 1,
                max_depth=max_depth,
                source_file=source_file,
                seen_ids=seen_ids,
                results=results,
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_json_schema_entities(
    filepath: str | Path,
    max_depth: int = 3,
) -> list[SourceEntity]:
    """Load a JSON Schema file and extract one :class:`SourceEntity` per property.

    Supports JSON Schema draft-07, draft-2019-09, and draft-2020-12.
    Recursively handles ``$defs``, ``definitions``, ``allOf``, ``anyOf``,
    ``oneOf``, and nested ``object`` types up to *max_depth*.

    Entity field conventions:

    * ``entity_id`` – ``"jschema:<schema_name>.<property_path>"`` where
      *property_path* uses dot notation for nesting.
    * ``label`` – the property name (last path component).
    * ``description`` – ``property["description"]`` or ``property["title"]``.
    * ``datatype`` – mapped from JSON Schema types to one of ``"string"``,
      ``"number"``, ``"boolean"``, ``"array"``, ``"object"``, ``"unknown"``.
    * ``examples`` – from ``property["examples"]`` and ``property["default"]``.
    * ``source_file`` – absolute path string.
    * ``source_type`` – ``"json_schema"``.
    * ``extra_context`` – ``json_schema_type``, ``format``, ``enum``,
      ``required``, ``parent_schema``, ``depth``.

    Args:
        filepath: Path to the JSON Schema file.
        max_depth: Maximum recursion depth for nested objects (default 3).

    Returns:
        A deduplicated list of :class:`SourceEntity` objects sorted by
        ``entity_id``.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        ValueError: If the file cannot be parsed as JSON.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"JSON Schema file not found: {filepath}")

    try:
        with filepath.open(encoding="utf-8") as fh:
            schema_root: dict[str, Any] = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse JSON file {filepath}: {exc}") from exc

    if not isinstance(schema_root, dict):
        return []

    source_file = str(filepath)
    # Use the file stem as the schema name, falling back to "title" if present
    schema_name = schema_root.get("title", filepath.stem)
    # Sanitise schema_name for use in entity_ids
    schema_name = str(schema_name).replace(" ", "_")

    results: list[SourceEntity] = []
    seen_ids: set[str] = set()

    # 1. Root-level properties
    root_required = set(schema_root.get("required", []))
    _extract_properties_recursive(
        schema=schema_root,
        schema_root=schema_root,
        schema_name=schema_name,
        path_parts=[],
        required_set=root_required,
        parent_schema=schema_name,
        depth=0,
        max_depth=max_depth,
        source_file=source_file,
        seen_ids=seen_ids,
        results=results,
    )

    # 2. $defs / definitions entries (each definition is a sub-schema)
    for defs_key in ("$defs", "definitions"):
        defs = schema_root.get(defs_key, {})
        if not isinstance(defs, dict):
            continue
        for def_name, def_schema in defs.items():
            if not isinstance(def_schema, dict):
                continue
            def_required = set(def_schema.get("required", []))
            _extract_properties_recursive(
                schema=def_schema,
                schema_root=schema_root,
                schema_name=schema_name,
                path_parts=[def_name],
                required_set=def_required,
                parent_schema=def_name,
                depth=1,
                max_depth=max_depth,
                source_file=source_file,
                seen_ids=seen_ids,
                results=results,
            )

    results.sort(key=lambda e: e.entity_id)
    return results

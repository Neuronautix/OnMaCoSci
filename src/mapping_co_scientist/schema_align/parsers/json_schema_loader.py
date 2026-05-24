"""Load a JSON Schema into SchemaEntity objects representing target paths."""
from __future__ import annotations
import json
from pathlib import Path
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity


def load_json_schema(path: Path) -> list[SchemaEntity]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entities: list[SchemaEntity] = []
    _walk_schema(data, prefix="", entities=entities, source_file=str(path))
    return entities


def _walk_schema(
    schema: dict,
    prefix: str,
    entities: list[SchemaEntity],
    source_file: str,
) -> None:
    if not isinstance(schema, dict):
        return

    schema_type = schema.get("type")

    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required_fields = set(schema.get("required", []))
        for key, sub_schema in props.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(sub_schema, dict):
                sub_type = sub_schema.get("type", "string")
                if sub_type == "object" or "properties" in sub_schema:
                    _walk_schema(sub_schema, path, entities, source_file)
                else:
                    entity = SchemaEntity(
                        entity_id=f"json:{path}",
                        path=path,
                        label=key.replace("_", " ").replace(".", " "),
                        datatype=sub_type if isinstance(sub_type, str) else "string",
                        format=sub_schema.get("format"),
                        description=sub_schema.get("description"),
                        required=(key in required_fields),
                        enumeration=sub_schema.get("enum", []),
                        source_file=source_file,
                        source_type="json_schema",
                    )
                    entities.append(entity)
    elif schema_type is not None and prefix:
        entity = SchemaEntity(
            entity_id=f"json:{prefix}",
            path=prefix,
            label=prefix.split(".")[-1].replace("_", " "),
            datatype=schema_type if isinstance(schema_type, str) else "string",
            format=schema.get("format"),
            description=schema.get("description"),
            source_file=source_file,
            source_type="json_schema",
        )
        entities.append(entity)

"""Load an OpenAPI spec into SchemaEntity objects."""
from __future__ import annotations
import json
from pathlib import Path
from mapping_co_scientist.schema_align.models.schema_entity import SchemaEntity


def load_openapi_schema(path: Path, target_schema_name: str | None = None) -> list[SchemaEntity]:
    data = json.loads(path.read_text(encoding="utf-8"))
    components = data.get("components", {}).get("schemas", {})
    entities: list[SchemaEntity] = []

    target = components
    if target_schema_name and target_schema_name in components:
        target = {target_schema_name: components[target_schema_name]}

    for schema_name, schema in target.items():
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        for field, defn in props.items():
            entity = SchemaEntity(
                entity_id=f"openapi:{schema_name}.{field}",
                path=f"{schema_name}.{field}",
                label=field.replace("_", " "),
                datatype=defn.get("type", "string"),
                description=defn.get("description"),
                required=(field in required),
                source_file=str(path),
                source_type="openapi",
            )
            entities.append(entity)
    return entities

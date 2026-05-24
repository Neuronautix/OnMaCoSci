# Skill: Schema Mapping

## What this skill does

Guides execution of the `schema-align` pipeline and structured review of the resulting field mapping candidates. Distinct from ontology alignment — this skill is for producing operational transformation rules that move data from a source schema to a target schema.

## When to invoke

Use this skill when:
- The user wants to map CSV columns to fields in a target JSON Schema
- The user needs to produce a YAML mapping specification or JSON transformation rules for an ETL pipeline
- The user wants to detect datatype mismatches, unit handling issues, or information loss between source and target
- The user needs constant assignments inferred from column name conventions (e.g., unit suffixes)

Do NOT use this skill for:
- Assigning SKOS predicates or ontology relations (use `ontology-alignment` skill)
- Producing SSSOM exports — schema-align never produces SSSOM
- Asserting semantic equivalence between concepts in formal ontologies

## Inputs required

| Input | Type | Notes |
|-------|------|-------|
| Source CSV | File path | Columns = source field names; first row = header |
| Target JSON Schema | File path | Defines target structure; see `examples/schema_align/inputs/metadatapp_import_schema.json` |
| Output directory | Directory path | Will be created if absent |

## Outputs produced

| File | Description |
|------|-------------|
| `field_mapping_candidates.json` | FieldMappingHypothesis objects with MappingOperation and TransformationRule |
| `approved_mapping_spec.yaml` | YAML mapping specification |
| `transformation_rules.json` | TransformationRule objects (JSON) |
| `transformation_validation_report.md` | Human review report with adversarial flags |
| `unmapped_fields_report.md` | Source fields with no suitable target |
| `information_loss_report.json` | Coverage metrics and lossy mapping list |

## Pipeline stages

1. **Source profiling** — Loads source CSV; infers datatypes, unit suffixes, cardinality
2. **Target profiling** — Loads target JSON Schema; creates `SchemaEntity` objects with nested path resolution
3. **Candidate generation** — Lexical matching + unit constant inference; assigns `MappingOperation` based on field structure
4. **Adversarial review** — Flags datatype mismatches, information loss, ambiguous count/index fields, missing unit assignments
5. **Rule generation** — Extracts `TransformationRule` from approved hypotheses
6. **Validation** — Datatype compatibility, cardinality checks, lossiness analysis
7. **Export** — Writes all output files

## Key concepts

### MappingOperation vocabulary

| Operation | Meaning |
|-----------|---------|
| `direct_copy` | Same type, same level; value copied as-is |
| `rename` | Same level, same type; field renamed |
| `nested_path` | Source field maps to a nested JSON path |
| `constant_assignment` | Target field always takes a fixed value (inferred from source column name convention) |
| `datatype_conversion` | Source and target have incompatible types |
| `unit_conversion` | Same dimension, different units (g → kg) |
| `enumeration_remapping` | Different controlled vocabulary values |
| `unmapped` | No suitable target found |

### Unit constant assignment pattern

When a source column name ends with a unit suffix (e.g., `_g`, `_kg`, `_C`, `_mm`):
1. The numeric value maps to a `measurements.*.value` path
2. The unit label maps to a `measurements.*.unit` path via `CONSTANT_ASSIGNMENT`

Example: `Weight_g` → `measurements.bodyWeight.value` (NESTED_PATH) + `measurements.bodyWeight.unit = "g"` (CONSTANT_ASSIGNMENT)

### ActivityCount and ambiguous fields

Fields named `ActivityCount`, `Index`, `Score`, or similar are flagged as ambiguous. The pipeline cannot determine from the column name alone whether this is a raw count, a derived index, or a normalised score. These fields require contextual clarification before a mapping can be approved.

## Example invocation

```
/schema-align \
  --source examples/schema_align/inputs/source_animal_records.csv \
  --target-schema examples/schema_align/inputs/metadatapp_import_schema.json \
  --output-dir examples/schema_align/outputs
```

# Schema Alignment Workflow

**Tool**: `schema-align` (`mapping_co_scientist.schema_align`)  
**Purpose**: Map fields between two operational schemas and generate reusable transformation rules.

---

## Overview

The schema alignment pipeline answers: **"How should data in field X of schema A be represented in field/path Y of schema B?"**

It produces:
- Field mapping candidates with transformation specifications
- Executable transformation rules
- Information loss report
- Unmapped fields report
- Human review report

**Critical distinction**: This tool does NOT use ontology predicates (SKOS, OWL), hierarchy reasoning, or SSSOM export. It is a data engineering tool, not an ontology curation tool.

---

## Pipeline Stages

### Stage 1: Source Schema Profiling

**Agent**: `SourceSchemaProfilerAgent`

Loads source fields from CSV or JSON and creates `SchemaEntity` objects:
- `path` — field path (e.g. `Weight_g`)
- `label` — human-readable name
- `datatype` — `"string"`, `"number"`, `"integer"`, `"boolean"`, `"array"`, `"object"`
- `unit` — physical unit inferred from column name suffix (e.g. `_g` → `"g"`)
- `examples` — representative values
- `enumeration` — allowed values if present
- `required` — whether the field is required

### Stage 2: Target Schema Profiling

**Agent**: `TargetSchemaProfilerAgent`

Loads target schema paths from JSON Schema or OpenAPI specs. For JSON Schema, recursively walks `properties` to build flat path list:
- `animal.externalId` → `SchemaEntity(path="animal.externalId")`
- `measurements.bodyWeight.value` → `SchemaEntity(path="measurements.bodyWeight.value")`
- `measurements.bodyWeight.unit` → `SchemaEntity(path="measurements.bodyWeight.unit")`

### Stage 3: Field Candidate Generation

**Agent**: `FieldCandidateGeneratorAgent`

Generates multiple `FieldMappingHypothesis` candidates per source field using lexical field matching (rapidfuzz WRatio).

**Mapping operations inferred**:

| Operation | When assigned |
|-----------|---------------|
| `direct_copy` | Same label, same datatype, high similarity (≥0.85) |
| `rename` | High similarity but labels differ |
| `nested_path` | Source is flat, target has nested path structure |
| `datatype_conversion` | Source and target datatypes differ |
| `constant_assignment` | Target field is a constant derived from source column name (e.g. unit) |
| `unmapped` | Similarity below threshold (0.25) |

**Special transformation detection**:
- `Weight_g` → `measurements.bodyWeight.value` (nested_path)
- `measurements.bodyWeight.unit` → constant `"g"` (from `_g` suffix in column name)
- `RecordingDate` → `measurements.activity.date` (rename + nested_path)

**Ambiguity detection**:
- `ActivityCount` is flagged as requiring contextual definition (count/index fields are ambiguous without knowing the sampling window, sensor type, and normalisation)

### Stage 4: Adversarial Review

**Agent**: `SchemaAdversarialReviewerAgent`

Flags:
- `datatype_mismatch` — incompatible source/target types (medium)
- `information_loss` — detected data loss (high)
- `unmapped_field` — no target path found (medium)
- `ambiguous_measurement` — count/index/score fields without contextual definition (medium)
- `unit_conversion_required` — unit mismatch (medium)
- `low_confidence` — confidence below 0.35 (medium)

### Stage 5: Validation

**Agent**: `SchemaValidationAgent`

Sets `ValidationStatus` on each hypothesis:
- `PASSED` — no issues
- `WARNING` — information loss detected, or DATATYPE_CONVERSION without expression

### Stage 6: Lossiness Analysis

**Function**: `build_lossiness_report`

Produces `LossinessReport`:
- Coverage percentage (mapped / total source fields)
- Unmapped field count
- Lossy mappings (with loss type and description)
- Ambiguous fields

### Stage 7: Export

**Exporters**:
- `generic_mapping_exporter.py` → `approved_mapping_spec.yaml`
- `transformation_spec_exporter.py` → `transformation_rules.json`
- `schema_review_report.py` → `transformation_validation_report.md`
- Unmapped fields report → `unmapped_fields_report.md`
- Information loss report → `information_loss_report.md` + `.json`

---

## Mapping Specification Format

The `approved_mapping_spec.yaml` uses a generic, format-neutral mapping specification:

```yaml
version: "1.0"
pipeline_run_id: sa-20240601T120000-abc123
mappings:
  - source_path: MouseID
    target_path: animal.externalId
    operation: nested_path
    confidence: 0.82
  - source_path: null
    target_path: measurements.bodyWeight.unit
    operation: constant_assignment
    constant_value: "g"
    confidence: 0.80
  - source_path: Weight_g
    target_path: measurements.bodyWeight.value
    operation: nested_path
    confidence: 0.75
    unit:
      from: "g"
      to: null
unmapped_fields:
  - source_path: ActivityCount
    reason: Requires contextual definition before safe reuse
human_review_required: []
```

This format is designed to be extended with:
- `expression` field for JSONata expressions (future)
- RML mappings when target is RDF (future, explicit flag required)

---

## Human Review Gate

The human reviewer may:
- **Approve** — accept the mapping and transformation rule
- **Reject** — reject the mapping
- **Modify** — change the target path, operation, or expression
- **Request more evidence** — defer for additional data profiling
- **Mark unmapped** — explicitly declare no mapping exists

**Lossy and information-losing mappings require mandatory human review before being marked approved.**

---

## Running the Example

```bash
python -m mapping_co_scientist.schema_align.cli \
  --source examples/schema_align/inputs/source_animal_records.csv \
  --target-schema examples/schema_align/inputs/metadatapp_import_schema.json \
  --output-dir examples/schema_align/outputs \
  --verbose
```

### Expected outputs

| File | Description |
|------|-------------|
| `field_mapping_candidates.json` | All hypotheses with transformation rules and warnings |
| `approved_mapping_spec.yaml` | Machine-readable mapping specification |
| `transformation_rules.json` | Executable transformation rule objects |
| `transformation_validation_report.md` | Human review report with adversarial flags |
| `unmapped_fields_report.md` | Fields with no suitable target |
| `information_loss_report.md` | Detected information loss |
| `information_loss_report.json` | Structured loss report |

---

## Where LLM Agents Will Be Used

Future LLM integration points (not yet implemented):
- **Field candidate generation**: LLM semantic matching beyond label similarity
- **Ambiguity detection**: LLM identifies when a field is semantically ambiguous (e.g. ActivityCount)
- **Transformation rule suggestion**: LLM proposes JSONata or Python expressions
- **Adversarial review**: LLM identifies subtle data engineering issues
- **Report synthesis**: LLM summarises the review packet

**Constraint**: An LLM must never directly approve mappings or silently generate executable transformations. All LLM outputs feed the hypothesis pipeline and require human approval before generating authoritative transformation rules.

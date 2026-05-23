# Mapping Co-Scientist

## What this project does

This repository contains two distinct CLI tools that share a common agentic review core:

1. **ontology-align** — Maps source concepts (CSV fields, OpenAPI params, JSON Schema properties) to terms in a formal ontology. Produces SKOS-predicated hypotheses, semantic warnings, SSSOM-compatible TSV, and term-gap proposals.

2. **schema-align** — Maps fields between two operational schemas (CSV to JSON, JSON to JSON, etc.). Produces transformation rules, a mapping specification YAML, lossiness reports, and unmapped field reports. Does NOT use SKOS predicates or SSSOM export.

## Package location

Source: `src/mapping_co_scientist/`  
Legacy source: `src/ontology_mapping_co_scientist/` (preserved, do not modify)

## CLI commands (invoke as Python modules — scripts not installed in PATH)

```bash
# Ontology alignment
python -m mapping_co_scientist.ontology_align.cli \
  --source <CSV_OR_JSON> \
  --ontology <YAML_OR_JSON_PROFILE> \
  --output-dir <DIR> \
  [--top-k 3] [--run-id <id>] [-v]

# Schema alignment
python -m mapping_co_scientist.schema_align.cli \
  --source <CSV_OR_JSON> \
  --target-schema <JSON_SCHEMA_OR_OPENAPI> \
  --output-dir <DIR> \
  [--top-k 3] [--run-id <id>] [-v]
```

## Output artifacts per run

### ontology-align outputs
- `ontology_mapping_candidates.json` — List of OntologyMappingHypothesis objects
- `ontology_mapping_candidates.sssom.tsv` — SSSOM-compliant mapping TSV
- `ontology_review_report.md` — Human-readable review report
- `term_gap_proposals.json` — Proposed new ontology terms

### schema-align outputs
- `field_mapping_candidates.json` — List of FieldMappingHypothesis objects
- `approved_mapping_spec.yaml` — Mapping specification (all candidates, not filtered)
- `transformation_rules.json` — Executable TransformationRule objects
- `transformation_validation_report.md` — Human-readable review report
- `unmapped_fields_report.md` — Fields with no suitable target
- `information_loss_report.json` — Structured lossiness analysis
- `information_loss_report.md` — Human-readable loss report

## Hypothesis status fields (both tools)

Every hypothesis in `*_candidates.json` has:
- `human_review_status`: starts as `awaiting_review` — must be explicitly set to `approved`/`rejected`
- `validation_status`: `pending` | `passed` | `warning` | `failed`

**Critical**: No mapping is approved or released until `human_review_status = "approved"` is explicitly set by a human reviewer. The pipeline never auto-approves.

## Mapping status lifecycle

```
candidate_generated
  → ai_reviewed          (Python pipeline adversarial + validation agents complete)
    → validation_pending
      → validation_failed   (blocking — do not proceed)
      → validation_passed
        → debate_complete  (three-agent SED protocol run by plugin commands)
          → human_review_required
            → human_approved    (safe to export/reuse)
            → human_rejected    (archived)
    → released_for_reuse  (ONLY after human_approved)
```

The `debate_complete` stage corresponds to the Structured Evidence Debate (SED) run by the plugin's three-agent system. The mediator's `debate_score` re-ranks candidates but does NOT change `human_review_status` — that still requires explicit human action.

## Critical constraints Claude must enforce

1. **Never auto-approve** any mapping. `human_approved` requires explicit human action.
2. **Never assign exactMatch** from lexical similarity alone (the generator enforces this — flag any exactMatch proposal for immediate ontology engineer review).
3. **Never emit SSSOM or SKOS predicates** from schema-align (only from ontology-align).
4. **Always report information-loss risks** before presenting schema mappings as complete.
5. **Do not fabricate validation results** — read them from the actual output JSON files.
6. **Do not release** a mapping set unless all top-1 hypotheses have `human_review_status = "approved"`.

## Example input files

Ontology-align example:
- Source: `examples/ontology_align/inputs/animal_fields.csv`
- Ontology: `examples/ontology_align/inputs/hcm_profile.yaml`

Schema-align example:
- Source: `examples/schema_align/inputs/source_animal_records.csv`
- Target: `examples/schema_align/inputs/metadatapp_import_schema.json`

## Running tests

```bash
python -m pytest tests/ -q
```

All 325 tests must pass before any pipeline changes are committed.

## Three-agent debate system (plugin commands)

Plugin commands run a Structured Evidence Debate (SED) for every mapping candidate. See `claude-plugin/agents/` for full definitions:

- `source-schema-advocate.md` — speaks for the source schema; argues FOR or AGAINST whether proposed mappings correctly characterise what the source field means; raises `ambiguity_unresolved`, `information_loss_risk`, `missing_unit_companion`, `domain_definition_match` arguments
- `target-schema-advocate.md` — speaks for the target schema/ontology; argues FOR or AGAINST whether proposed predicates/operations are semantically appropriate; raises `semantic_overreach`, `type_incompatibility`, `operation_safety`, `scope_relationship` arguments
- `mapping-mediator.md` — runs debate rounds; applies Elo ranking (initial Elo from pipeline confidence; pairwise K-weighted updates per argument; flat Elo penalties for blocking conditions); re-ranks candidates; produces cross-mapping consistency report (collisions, symmetry violations, rank inversions, coverage)

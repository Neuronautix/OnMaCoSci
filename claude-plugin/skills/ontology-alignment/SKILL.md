# Skill: Ontology Alignment

## What this skill does

Guides execution of the `ontology-align` pipeline and structured review of the resulting SKOS-based ontology mapping candidates. Distinct from schema mapping — this skill is for asserting semantic relationships between biological/scientific concepts and terms in a formal ontology.

## When to invoke

Use this skill when:
- The user wants to map column headers or concept labels from a CSV to terms in an OWL/SKOS ontology
- The user wants to produce an SSSOM-compliant export of concept mappings
- The user needs to identify which source concepts have no suitable ontology term (term gap analysis)
- The user needs SKOS relation assignments with semantic scope analysis

Do NOT use this skill for:
- Mapping operational CSV/JSON fields to a target JSON Schema (use `schema-mapping` skill)
- Producing ETL transformation rules (use `schema-mapping` skill)

## Inputs required

| Input | Type | Notes |
|-------|------|-------|
| Source CSV | File path | Columns = concept labels; one row = one source concept |
| Ontology profile YAML | File path | Defines terms, types, hierarchy; see `examples/ontology_align/inputs/hcm_profile.yaml` |
| Output directory | Directory path | Will be created if absent |

## Outputs produced

| File | Description |
|------|-------------|
| `ontology_mapping_candidates.json` | OntologyMappingHypothesis objects with SKOS relations, evidence, warnings |
| `ontology_mapping_candidates.sssom.tsv` | SSSOM-compliant TSV with metadata header |
| `ontology_review_report.md` | Human-readable review grouped by source entity |
| `term_gap_proposals.json` | Proposed new terms for unmapped source concepts |

## Pipeline stages

1. **Source profiling** — Loads source CSV; creates `SourceEntity` objects with entity type inference (identifier, attribute, measurement)
2. **Ontology profiling** — Loads ontology YAML; indexes all terms with labels, types, hierarchy
3. **Candidate generation** — Lexical matching using rapidfuzz WRatio; assigns at most `skos:closeMatch` for high-scoring pairs (never auto-exactMatch)
4. **Adversarial review** — Flags identifier→class mismatches, exactMatch overreach, measurement→class mismatches
5. **Term gap analysis** — Identifies source concepts with no match above confidence threshold
6. **Validation** — Checks SKOS predicate appropriateness; produces `ValidationStatus` per hypothesis
7. **Export** — Writes all output files

## Key constraints

- `skos:exactMatch` is NEVER assigned automatically; it requires explicit human approval
- `strain → GeneticBackground` must use `skos:narrowMatch` (strain is narrower than genetic background)
- `skos:closeMatch` is the default for high lexical similarity; humans upgrade to exactMatch if warranted
- Identifier source fields should not map to OWL classes
- SSSOM export is only produced by this skill, never by schema-mapping

## Example invocation

```
/ontology-align \
  --source examples/ontology_align/inputs/animal_fields.csv \
  --ontology examples/ontology_align/inputs/hcm_profile.yaml \
  --output-dir examples/ontology_align/outputs
```

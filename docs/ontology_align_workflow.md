# Ontology Alignment Workflow

**Tool**: `ontology-align` (`mapping_co_scientist.ontology_align`)  
**Purpose**: Map source concepts to ontology terms and generate semantically meaningful alignment suggestions.

---

## Overview

The ontology alignment pipeline answers the question: **"Does source concept X correspond semantically to ontology entity Y?"**

It produces:
- Ranked ontology mapping hypotheses with SKOS predicates
- Semantic warnings and adversarial review flags
- SSSOM-compatible TSV export
- Term gap proposals for missing ontology terms
- Human review report

---

## Pipeline Stages

### Stage 1: Source Profiling

**Agent**: `OntologySourceProfilerAgent`

Loads source concepts from CSV, JSON, or other formats and converts them into `SourceEntity` objects:
- `entity_id` — unique path identifier (e.g. `csv:animal.strain`)
- `label` — raw field name
- `datatype` — inferred from values
- `examples` — representative sample values
- `source_type` — `"csv"`, `"openapi"`, `"json_schema"`, etc.

### Stage 2: Ontology Profiling

**Agent**: `OntologyTargetProfilerAgent`

Loads ontology terms from YAML profiles, JSON-LD, or RDF/OWL files into `OntologyTerm` objects:
- `term_id` — CURIE or IRI (e.g. `hcm:GeneticBackground`)
- `label` — preferred label
- `definition` — formal definition (IAO:0000115 or skos:definition)
- `synonyms` — exact, broad, and narrow synonyms
- `parent_terms` — rdfs:subClassOf or skos:broader
- `term_type` — `"class"`, `"property"`, `"individual"`

Builds a label index including synonyms for matching.

### Stage 3: Candidate Generation

**Agent**: `SemanticCandidateGeneratorAgent`

Generates multiple `OntologyMappingHypothesis` candidates per source entity.

**Current implementation**: lexical similarity baseline (rapidfuzz WRatio)  
**Future**: LLM-backed semantic scoring

**Critical constraint**: Lexical similarity alone **cannot** establish `skos:exactMatch`. The generator assigns at most `skos:closeMatch` for high-scoring pairs and adds a semantic warning requiring expert validation before upgrading to exactMatch.

**Special case** (required by spec): `strain → GeneticBackground` is detected as a narrower-scope match, not a close or exact match. `strain` is a specific genetic lineage; `GeneticBackground` includes genotype, breeding history, and more.

### Stage 4: Adversarial Review

**Agent**: `OntologyAdversarialReviewerAgent`

Inspects each hypothesis for:
- `exactmatch_requires_validation` — exactMatch proposed without semantic validation (high severity)
- `owl_equivalence_overreach` — owl:equivalentClass/Property used without OWL reasoning (high severity)
- `low_confidence` — confidence below 0.40 (medium severity)
- `missing_ontology_definition` — target term lacks a formal definition (low severity)
- `measurement_to_class_mismatch` — source is a measurement, target is a class (medium severity)
- `identifier_to_class_mismatch` — identifier mapped to a class instead of a property (medium severity)
- Semantic warnings from candidate generator (propagated)

### Stage 5: Validation

**Agent**: `OntologyValidationAgent`

Sets `ValidationStatus` on each hypothesis:
- `PASSED` — no issues detected
- `WARNING` — one or more non-fatal concerns (e.g. exactMatch without justification)
- `FAILED` — blocking issues

### Stage 6: Term Gap Identification

**Agent**: `TermGapAgent`

Identifies source entities with no suitable ontology mapping (no hypothesis with confidence ≥ 0.40 and non-NO_MAPPING relation) and generates `TermGapProposal` stubs for expert review. These are **proposals only** — the tool never modifies an ontology.

### Stage 7: Export

**Exporters**:
- `sssom_exporter.py` — SSSOM-compliant TSV with metadata header
- `ontology_review_report.py` — Markdown report grouped by source entity
- `jsonld_exporter.py` — JSON-LD stub (future implementation)
- Term gap proposals as JSON

---

## Ontology Relation Predicates

| Predicate | When to use |
|-----------|-------------|
| `skos:exactMatch` | Full semantic interchangeability — requires expert validation, NEVER auto-assigned |
| `skos:closeMatch` | Very similar for most practical purposes |
| `skos:broadMatch` | Target is more general than source |
| `skos:narrowMatch` | Target is more specific than source |
| `skos:relatedMatch` | Related but no directional hierarchy |
| `rdfs:subClassOf` | Source class is a subclass of target class |
| `owl:equivalentClass` | Logical equivalence — requires OWL reasoning, never auto-assigned |
| `owl:equivalentProperty` | Property equivalence — requires OWL reasoning, never auto-assigned |
| `custom:requiresOntologyExtension` | No suitable term; ontology gap identified |
| `custom:noSuitableMapping` | No suitable term and no extension proposed |
| `custom:requiresHumanDecision` | Ambiguous; human must decide |

---

## Human Review Gate

The human reviewer may:
- **Approve** — accept the mapping as proposed
- **Reject** — reject the mapping
- **Change relation** — e.g. downgrade from closeMatch to narrowMatch
- **Request more evidence** — defer for additional research
- **Propose new term** — request an ontology extension

**Important**: The tool never modifies an ontology. Term gap proposals require explicit expert approval and a formal ontology engineering process.

---

## Running the Example

```bash
python -m mapping_co_scientist.ontology_align.cli \
  --source examples/ontology_align/inputs/animal_fields.csv \
  --ontology examples/ontology_align/inputs/hcm_profile.yaml \
  --output-dir examples/ontology_align/outputs \
  --verbose
```

### Expected outputs

| File | Description |
|------|-------------|
| `ontology_mapping_candidates.json` | All hypotheses with evidence and warnings |
| `ontology_mapping_candidates.sssom.tsv` | SSSOM-compliant mapping export |
| `ontology_review_report.md` | Human review report with flags and alternatives |
| `term_gap_proposals.json` | Proposed new ontology terms for unmapped concepts |

---

## Where LLM Agents Will Be Used

Future LLM integration points (not yet implemented):
- **Semantic candidate generation**: Replace lexical baseline with LLM semantic scoring
- **Ambiguity detection**: LLM identifies when source concept is semantically ambiguous
- **Adversarial review**: LLM critic identifies subtle ontological errors
- **Term gap proposal enrichment**: LLM drafts formal definitions for proposed terms
- **Report synthesis**: LLM summarises the review packet for the human reviewer

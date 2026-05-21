# MappingHypothesis Data Model

This document is the authoritative specification for the `MappingHypothesis`
data model and its supporting types.  It covers field definitions, valid
values, the mapping predicate vocabulary, evidence and provenance models,
lifecycle states, alignment with the SSSOM standard, and worked examples.

---

## Overview

A `MappingHypothesis` is the central data structure of the ontology mapping
pipeline.  It represents a single proposed link between:

- a **source entity** (`SourceEntity`) — a field, column, or property from a
  real-world data source
- a **target entity** (`OntologyTerm`) — a term in a formal ontology

Every hypothesis carries:
- the nature of the proposed relationship (a SKOS predicate)
- a confidence score reflecting the pipeline's certainty
- a list of supporting evidence items
- a list of counter-evidence items
- adversarial warnings
- automated validation status
- human review status
- provenance metadata

A hypothesis is not a mapping until a human reviewer approves it.

---

## MappingHypothesis fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mapping_id` | `str` | Yes | Globally unique identifier within the pipeline run.  Convention: `map_<safe_entity_id>_<safe_term_id>_<rank>` |
| `source_entity` | `SourceEntity` | Yes | The source entity being mapped (left-hand side) |
| `target_entity` | `OntologyTerm` | Yes | The candidate ontology term (right-hand side).  May be `null` for `NO_MAPPING` hypotheses |
| `predicate` | `MappingPredicate` | Yes | The SKOS predicate describing the relationship |
| `confidence` | `float` [0.0, 1.0] | Yes | Aggregate confidence score produced by the pipeline |
| `evidence` | `list[Evidence]` | No | Supporting evidence items, in order of addition |
| `counter_evidence` | `list[Evidence]` | No | Evidence items arguing against the mapping |
| `required_conditions` | `list[str]` | No | Conditions that must hold for the mapping to be valid |
| `reviewer_notes` | `list[str]` | No | Free-text notes added by human reviewers |
| `validation_status` | `ValidationStatus` | No | Automated validation lifecycle state (default: `pending`) |
| `human_review_status` | `HumanReviewStatus` | No | Human review lifecycle state (default: `awaiting_review`) |
| `warnings` | `list[str]` | No | Non-fatal warning messages from any pipeline stage |
| `provenance` | `Provenance` | Yes | Provenance metadata for audit and reproducibility |
| `rank` | `int ≥ 1 \| None` | No | Rank among candidates for the same source entity; 1 = best. `None` until ranking is performed |

---

## SourceEntity fields

| Field | Type | Description |
|-------|------|-------------|
| `entity_id` | `str` | Unique identifier: `<source_type>:<stem>.<field>`, e.g. `csv:animal.strain` |
| `label` | `str` | Human-readable field name from the source artefact |
| `description` | `str \| None` | Description from the source artefact, if available |
| `datatype` | `str \| None` | Declared primitive type: `string`, `number`, `boolean`, `integer`, `array` |
| `examples` | `list[str]` | Representative sample values (up to 3 from CSV, 1 from OpenAPI) |
| `source_file` | `str \| None` | Path or URL of the originating artefact |
| `source_type` | `str` | Kind of artefact: `csv`, `openapi`, `json_schema`, `database_column` |
| `extra_context` | `dict` | Arbitrary additional metadata attached by the extractor |

---

## OntologyTerm fields

| Field | Type | Description |
|-------|------|-------------|
| `term_id` | `str` | CURIE or IRI, e.g. `mbo:GeneticBackground` or `http://purl.obolibrary.org/obo/MBO_0001234` |
| `label` | `str` | Preferred label (`rdfs:label` or `skos:prefLabel`) |
| `definition` | `str \| None` | Formal definition (`IAO:0000115` or `skos:definition`) |
| `synonyms` | `list[str]` | Exact, broad, and narrow synonyms |
| `parent_terms` | `list[str]` | Direct superclasses or broader concepts |
| `term_type` | `str` | Logical type: `class`, `property`, `individual`, `annotation_property` |
| `ontology_id` | `str` | Short ontology identifier: `mbo`, `ncit`, `hp`, `chebi` |
| `ontology_source` | `str \| None` | URL or file path the term was loaded from |
| `extra_context` | `dict` | Additional metadata (subset membership, cross-references, etc.) |

---

## Mapping predicates

The predicate vocabulary is based on
[SKOS (Simple Knowledge Organization System)](https://www.w3.org/TR/skos-reference/)
with two custom extensions for cases that SKOS does not cover.

### `skos:exactMatch`

**Semantic definition**: The source entity and the ontology term can be used
interchangeably in any context without loss of meaning.  This implies a
bidirectional equivalence relationship.

**When to use**: Use only when the definitions are semantically identical, the
datatypes are compatible, and no transformation is required.  This is the
strongest mapping predicate and should be used conservatively.

**Typical confidence range**: > 0.85

**Example**: CSV column `strain` (string, values: "C57BL/6", "BALB/c") maps
exactly to `mbo:MouseStrain` which is defined as "a genetically distinct mouse
lineage".

---

### `skos:closeMatch`

**Semantic definition**: The source entity and the ontology term are
sufficiently similar for most practical purposes but are not strictly
interchangeable.  There may be minor definitional differences, scope
differences, or granularity differences.

**When to use**: Use when the concepts are clearly about the same thing but the
definitions are not precisely equivalent, or when there is some uncertainty
about full equivalence.  This is the appropriate conservative default when
you are not sure whether `exactMatch` applies.

**Typical confidence range**: 0.60–0.85

**Example**: CSV column `genetic background` maps to `mbo:GeneticBackground`.
The labels are essentially the same but the source column may contain
freetext values while the ontology term implies a controlled vocabulary.

---

### `skos:broadMatch`

**Semantic definition**: The ontology term is semantically broader (more
general) than the source entity.  The source entity's meaning is a
specialisation or subtype of the ontology term.

**When to use**: Use when the source entity is a specific case of a more
general ontology concept, and no more specific ontology term exists in the
current profile.

**Example**: CSV column `tumor grade` (values: "Grade I", "Grade II", "Grade
III") maps to `ncit:TumorGrade` with `broadMatch` if the ontology only defines
`TumorGrade` at the general level and not the specific grade values.

---

### `skos:narrowMatch`

**Semantic definition**: The ontology term is semantically narrower (more
specific) than the source entity.  The source entity encompasses the ontology
term but also covers additional cases not represented by the term.

**When to use**: Use when the ontology term is a specific subtype of what the
source entity is capturing, and using the term would lose information.

**Example**: Source entity `animal identifier` maps to `mbo:MouseEarTagID`
with `narrowMatch` because the source captures any identifier, while the
ontology term is specific to ear tag numbers.

---

### `skos:relatedMatch`

**Semantic definition**: The two concepts are related but the relationship is
not directional and does not fit exactMatch, closeMatch, broadMatch, or
narrowMatch.

**When to use**: Use sparingly, only when there is a clear semantic
relationship that does not fit any of the directional predicates.  If you are
unsure whether to use `relatedMatch` or `closeMatch`, prefer `closeMatch`.

---

### `custom:requiresTransform`

**Semantic definition**: A mapping exists between the source entity and the
ontology term, but the source values must be transformed before they are
semantically equivalent to the ontology term's expected values.  Common
transformation types: unit conversion, string normalisation, enumeration
mapping, numeric binning.

**When to use**: Use when the conceptual mapping is sound but a value-level
transformation is required.  The `required_conditions` field on the hypothesis
should document the transformation precisely.

**Example**: Source entity `body weight` in grams maps to `mbo:BodyWeight` in
kilograms.  The mapping is semantically exact, but the values must be divided
by 1000.

---

### `custom:noMapping`

**Semantic definition**: No suitable ontology term was found in the current
profile for this source entity.  This is not a failure — it is an explicit
signal that a domain expert must determine whether (a) an existing term was
missed, (b) a related term should be used with a broader predicate, or (c) a
new ontology term should be requested.

**When to use**: Automatically assigned by the `CandidateGeneratorAgent` when
no candidate exceeds the minimum confidence threshold.

**Target entity**: `null` for `NO_MAPPING` hypotheses.

---

## Evidence model

An `Evidence` object represents one piece of information that supports (or
contradicts) a mapping hypothesis.

| Field | Type | Description |
|-------|------|-------------|
| `evidence_type` | `str` | Machine-readable tag: see well-known values below |
| `description` | `str` | Human-readable explanation |
| `score` | `float [0.0, 1.0] \| None` | Normalised score, or `None` if qualitative |
| `source` | `str \| None` | Agent or module that produced this evidence |

### Well-known `evidence_type` values

| Value | Produced by | Description |
|-------|-------------|-------------|
| `lexical_similarity` | `CandidateGeneratorAgent` | Score from fuzzy string matching between source label and preferred label |
| `synonym_match` | `CandidateGeneratorAgent` | Score from fuzzy matching against ontology synonym |
| `definition_match` | (planned) `DefinitionMatchingAgent` | Semantic similarity between source description and ontology definition |
| `embedding_similarity` | (planned) `EmbeddingAgent` | Cosine similarity in embedding space |
| `parent_term_overlap` | (planned) `HierarchyAgent` | Overlap in parent term sets |
| `example_value_match` | (planned) `ExampleValueAgent` | Match between source example values and ontology individuals/enums |
| `datatype_compatibility` | (planned) `DatatypeAgent` | Score reflecting datatype compatibility |

---

## Provenance model

`Provenance` records the origin and history of a hypothesis.

| Field | Type | Description |
|-------|------|-------------|
| `created_by` | `str` | Agent name or `"human"` |
| `created_at` | `str` | ISO 8601 UTC datetime, e.g. `"2025-03-15T14:22:00+00:00"` |
| `method` | `str` | Short method identifier, e.g. `"lexical_similarity_v1"` |
| `pipeline_run_id` | `str \| None` | Run identifier for traceability |
| `extra` | `dict` | Additional provenance metadata (model version, config hash, etc.) |

---

## Validation status lifecycle

`ValidationStatus` is set by the `ValidationAgent` and reflects the outcome
of automated checks.  It does not reflect human judgement.

```
PENDING ──► PASSED
        ──► WARNING
        ──► FAILED
```

| Status | Meaning |
|--------|---------|
| `pending` | Not yet validated; initial state |
| `passed` | All automated checks passed; no warnings |
| `warning` | Checks passed but non-fatal issues were found; noted in `warnings` |
| `failed` | One or more checks failed; hypothesis should not be promoted without remediation |

A `failed` validation does not prevent human review; it is a strong signal
that the reviewer should examine the mapping carefully.

---

## Human review status lifecycle

`HumanReviewStatus` is set by a human reviewer (or by a simulation of the
human review step in automated testing).

```
AWAITING_REVIEW ──► APPROVED
                ──► REJECTED
                ──► NEEDS_MORE_EVIDENCE ──► (back to AWAITING_REVIEW after investigation)
                ──► PREDICATE_CHANGED
                ──► NEW_TERM_REQUESTED
```

| Status | Meaning | Sets by action |
|--------|---------|---------------|
| `awaiting_review` | Initial state; review not yet started | — |
| `approved` | Reviewer accepts the mapping as proposed | `HumanReviewAction.APPROVE` |
| `rejected` | Reviewer rejects the mapping entirely | `HumanReviewAction.REJECT` |
| `needs_more_evidence` | Reviewer wants additional evidence before deciding | `HumanReviewAction.REQUEST_MORE_EVIDENCE` |
| `predicate_changed` | Reviewer accepts the target but changes the predicate | `HumanReviewAction.CHANGE_PREDICATE` |
| `new_term_requested` | Reviewer requests creation of a new ontology term | `HumanReviewAction.CREATE_NEW_TERM` |

Only hypotheses with `human_review_status = approved` or `predicate_changed`
should be promoted to authoritative mapping sets.

---

## SSSOM alignment notes

The [Simple Standard for Sharing Ontological Mappings
(SSSOM)](https://mapping-commons.github.io/sssom/) is the community standard
for mapping serialisation.  The `MappingHypothesis` model is designed to be
alignable with SSSOM, but full conformance is not yet achieved.

| SSSOM field | `MappingHypothesis` equivalent | Notes |
|-------------|-------------------------------|-------|
| `subject_id` | `source_entity.entity_id` | Not an IRI; pipeline-internal identifier |
| `subject_label` | `source_entity.label` | |
| `predicate_id` | `predicate` | SKOS CURIEs map directly; custom predicates require local resolution |
| `object_id` | `target_entity.term_id` | CURIE or IRI form |
| `object_label` | `target_entity.label` | |
| `mapping_justification` | `evidence[0].description` | SSSOM expects an IRI from the SEMAPV vocabulary |
| `confidence` | `confidence` | Same range [0.0, 1.0] |
| `creator_id` | `provenance.created_by` | SSSOM expects an ORCID or IRI; pipeline uses agent names |
| `mapping_date` | `provenance.created_at` | Format compatible after ISO 8601 parsing |
| `mapping_set_id` | (not yet assigned) | Requires IRI scheme for the mapping set |
| `comment` | `warnings` (joined) | |

**Full SSSOM conformance requires**:
- ORCID or IRI for `creator_id`
- Mapping set IRI
- `mapping_justification` from the SEMAPV vocabulary (not free text)
- Serialisation in the SSSOM metadata header format

These are planned for Phase 4 of the roadmap.

---

## Examples

### Well-formed hypothesis (high confidence, approved)

```json
{
  "mapping_id": "map_csv_animal_strain_mbo_MouseStrain_0",
  "source_entity": {
    "entity_id": "csv:animal.strain",
    "label": "strain",
    "description": null,
    "datatype": "string",
    "examples": ["C57BL/6", "BALB/c", "129/Sv"],
    "source_file": "data/animals.csv",
    "source_type": "csv",
    "extra_context": {"column_name": "strain", "total_rows": 150}
  },
  "target_entity": {
    "term_id": "mbo:MouseStrain",
    "label": "mouse strain",
    "definition": "A genetically distinct lineage of laboratory mice maintained by inbreeding.",
    "synonyms": ["strain", "genetic background", "mouse line"],
    "parent_terms": ["mbo:BiologicalCharacteristic"],
    "term_type": "class",
    "ontology_id": "mbo",
    "ontology_source": "examples/ontology_profiles/hcm_mouse_profile.yaml",
    "extra_context": {}
  },
  "predicate": "skos:closeMatch",
  "confidence": 0.8750,
  "evidence": [
    {
      "evidence_type": "lexical_similarity",
      "description": "Token sort ratio between 'strain' and 'mouse strain': 0.857",
      "score": 0.857,
      "source": "CandidateGeneratorAgent"
    },
    {
      "evidence_type": "synonym_match",
      "description": "Source label 'strain' matches synonym 'strain' exactly: 1.000",
      "score": 1.0,
      "source": "CandidateGeneratorAgent"
    }
  ],
  "counter_evidence": [],
  "required_conditions": [],
  "reviewer_notes": [
    "Confirmed: example values C57BL/6 and BALB/c are standard mouse strains. Approved."
  ],
  "validation_status": "passed",
  "human_review_status": "approved",
  "warnings": [],
  "provenance": {
    "created_by": "CandidateGeneratorAgent",
    "created_at": "2025-03-15T14:22:00+00:00",
    "method": "lexical_similarity_v1",
    "pipeline_run_id": "run-2025-03-15-001",
    "extra": {}
  },
  "rank": 1
}
```

---

### Poorly-formed hypothesis (missing evidence, wrong predicate, no provenance detail)

```json
{
  "mapping_id": "map-001",
  "source_entity": {
    "entity_id": "x",
    "label": "sex",
    "description": null,
    "datatype": null,
    "examples": [],
    "source_file": null,
    "source_type": "unknown",
    "extra_context": {}
  },
  "target_entity": {
    "term_id": "ncit:Sex",
    "label": "Sex",
    "definition": null,
    "synonyms": [],
    "parent_terms": [],
    "term_type": "class",
    "ontology_id": "ncit",
    "ontology_source": null,
    "extra_context": {}
  },
  "predicate": "skos:exactMatch",
  "confidence": 0.9500,
  "evidence": [],
  "counter_evidence": [],
  "required_conditions": [],
  "reviewer_notes": [],
  "validation_status": "warning",
  "human_review_status": "awaiting_review",
  "warnings": [
    "Mapping hypothesis has no supporting evidence items. Confidence score cannot be independently verified.",
    "Source entity label 'sex' is very short (1 word, ≤4 characters). Short labels are prone to spurious matches."
  ],
  "provenance": {
    "created_by": "unknown",
    "created_at": "2025-01-01T00:00:00Z",
    "method": "manual",
    "pipeline_run_id": null,
    "extra": {}
  },
  "rank": null
}
```

Problems with this hypothesis:
- `entity_id` is `"x"` — not following the `<source_type>:<stem>.<field>` convention
- `datatype` is `null` — should be inferred or declared
- `examples` is empty — no values to inform semantic review
- `target_entity.definition` is `null` — cannot verify semantic accuracy
- `confidence` is 0.95 but `evidence` is empty — unjustified confidence
- `predicate` is `exactMatch` — a strong claim with no supporting evidence
- `rank` is `null` — ranking was never performed
- `human_review_status` is `awaiting_review` — never reviewed despite high confidence

---

### NO_MAPPING hypothesis

```json
{
  "mapping_id": "map_csv_sample_tumor_grade_NO_MAPPING_0",
  "source_entity": {
    "entity_id": "csv:sample.tumor_grade",
    "label": "tumor grade",
    "description": null,
    "datatype": "string",
    "examples": ["Grade I", "Grade II", "Grade III"],
    "source_file": "data/samples.csv",
    "source_type": "csv",
    "extra_context": {}
  },
  "target_entity": null,
  "predicate": "custom:noMapping",
  "confidence": 0.0,
  "evidence": [],
  "counter_evidence": [],
  "required_conditions": [],
  "reviewer_notes": [],
  "validation_status": "warning",
  "human_review_status": "awaiting_review",
  "warnings": [
    "The top-ranked hypothesis for this source entity is NO_MAPPING. Consider whether any existing term could serve as a partial match."
  ],
  "provenance": {
    "created_by": "CandidateGeneratorAgent",
    "created_at": "2025-03-15T14:22:01+00:00",
    "method": "lexical_similarity_v1",
    "pipeline_run_id": "run-2025-03-15-001",
    "extra": {}
  },
  "rank": 1
}
```

For this hypothesis, the suggested human action would be `create_new_ontology_term`.
The reviewer should check whether "tumor grade" (or "pathological grade",
"Scarff-Bloom-Richardson grade", etc.) exists in a broader oncology ontology
that was not included in the current profile.

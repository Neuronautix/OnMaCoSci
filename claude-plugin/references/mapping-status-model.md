# Mapping Status Model

## Overview

Every mapping hypothesis produced by the pipeline carries two status fields that independently track machine validation and human review:

| Field | Type | Tracks |
|-------|------|--------|
| `validation_status` | `ValidationStatus` | Machine-computed validity of the hypothesis |
| `human_review_status` | `HumanReviewStatus` | Human decision on whether to accept the mapping |

A mapping is not complete until **both** fields reflect a terminal state.

---

## ValidationStatus

Defined in `src/mapping_co_scientist/shared/models/review.py`.

| Value | Meaning | Who sets it |
|-------|---------|-------------|
| `pending` | Not yet validated | Pipeline initialisation |
| `passed` | All validation checks pass | `OntologyValidationAgent` / `SchemaValidationAgent` |
| `warning` | Validation completed; one or more non-blocking issues | Validation agents |
| `failed` | One or more blocking validation issues | Validation agents |

### Ontology validation checks (OntologyValidationAgent)
- SKOS predicate appropriate for source/target entity type pair
- OWL hierarchy compatibility (no cycles, consistent domain/range)
- Semantic scope confirmed for narrowMatch/broadMatch

### Schema validation checks (SchemaValidationAgent)
- Target path exists in the target schema
- Datatype compatibility for the assigned MappingOperation
- Cardinality constraints satisfied
- Unit dimension compatibility for unit conversion operations

---

## HumanReviewStatus

Defined in `src/mapping_co_scientist/shared/models/review.py`.

| Value | Meaning | Terminal? |
|-------|---------|-----------|
| `awaiting_review` | No human decision yet | No |
| `approved` | Human accepted the mapping | Yes |
| `rejected` | Human discarded the mapping | Yes |
| `needs_more_evidence` | Human deferred; more information needed | No |
| `predicate_changed` | Human changed the SKOS relation (ontology runs only) | Yes |
| `new_term_requested` | No suitable target; human initiated term gap proposal (ontology runs only) | Yes |

---

## Full mapping lifecycle

```
┌─────────────────────────┐
│   candidate_generated   │  Pipeline generates hypothesis
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│       ai_reviewed       │  Adversarial reviewer applies flags
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│   validation_pending    │  Queued for validation agent
└────────────┬────────────┘
             │
      ┌──────┴──────┐
      │             │
      ▼             ▼
┌──────────┐  ┌───────────┐
│validation│  │ validation│
│  passed  │  │  failed   │
└─────┬────┘  └─────┬─────┘
      │             │
      │         (blocked;       
      │         human must      
      │         override or     
      │         reject)         
      │
      ▼
┌─────────────────────────┐
│  human_review_required  │  Plugin commands present to human
└────────────┬────────────┘
             │
      ┌──────┼──────┬──────────────────┐
      │      │      │                  │
      ▼      ▼      ▼                  ▼
┌─────────┐ ┌──────────┐ ┌──────────────────┐ ┌────────────────────┐
│approved │ │ rejected │ │needs_more_evidence│ │predicate_changed / │
│         │ │          │ │ (re-enters queue) │ │new_term_requested  │
└────┬────┘ └──────────┘ └──────────────────┘ └────────────────────┘
     │
     ▼
┌─────────────────────────┐
│   released_for_reuse    │  Safe to include in export / downstream use
└─────────────────────────┘
```

---

## Enforcement rules for plugin commands

1. **No auto-approval**: Plugin commands must never advance `human_review_status` from `awaiting_review` to `approved` without an explicit user decision.

2. **Validation must pass before export**: `/validate-and-export` must check that no hypothesis has `validation_status: failed` before writing output files (unless `--force` is explicitly set and user confirms).

3. **No exactMatch without human upgrade**: `skos:exactMatch` must not appear in any hypothesis that has not been explicitly approved by a human reviewer. The generator assigns `skos:closeMatch` at most.

4. **Information loss requires acknowledgement**: Any hypothesis with `information_loss: true` must have explicit human acknowledgement before it can be marked `approved`.

5. **Terminal states are final**: Once `approved` or `rejected`, a hypothesis status should not be changed by the plugin without the user explicitly requesting a re-review.

---

## Status field locations in JSON output files

### Ontology alignment (`ontology_mapping_candidates.json`)
```json
{
  "mapping_id": "...",
  "human_review_status": "awaiting_review",
  "validation_status": "passed",
  ...
}
```

### Schema alignment (`field_mapping_candidates.json`)
```json
{
  "mapping_id": "...",
  "human_review_status": "awaiting_review",
  "validation_status": "passed",
  ...
}
```

Both files use identical field names for these two status fields, making the review commands work uniformly across run types.

# Skill: Mapping Review

## What this skill does

Provides structured human-in-the-loop review of pipeline-generated mapping candidates. Works with existing output directories from either the `ontology-align` or `schema-align` pipeline. Uses a three-agent Structured Evidence Debate (source advocate, target advocate, mediator) to prioritise review.

## When to invoke

Use this skill when:
- A pipeline run has already completed and the user needs to review the candidates
- The user wants debate-based challenge from source and target perspectives
- The user wants to batch-process a review queue with tiered prioritisation
- The user needs a cross-mapping consistency check from the mediator report

## Debate roles

| Role | Focus |
|------|-------|
| Source Schema Advocate | Whether mappings faithfully represent source meaning and context |
| Target Schema Advocate | Whether target semantics, predicates, and operations are appropriate |
| Mapping Mediator | Elo-based ranking, penalties, and cross-mapping consistency checks |

## Review lifecycle

Each hypothesis moves through this lifecycle:

```
candidate_generated → ai_reviewed → validation_pending
  → validation_passed/failed → human_review_required
  → human_approved/human_rejected → released_for_reuse
```

The `/review-mappings` command handles the `human_review_required → human_approved/human_rejected` transition. It does NOT persist decisions back to JSON in v0.2.0 (review ledger not yet implemented).

## Review prioritisation

Items are sorted into three tiers for efficient review:

**Tier 1** (review first, one at a time):
- High-severity adversarial flags
- Information loss detected
- Confidence < 0.50

**Tier 2** (standard review):
- Medium-severity adversarial flags
- Confidence 0.50–0.70

**Tier 3** (bulk review candidates):
- Clean or low-severity flags
- Confidence >= 0.85
- Note: bulk approval still requires explicit user confirmation per item

## Available human review actions

### Ontology alignment decisions

| Action | Effect |
|--------|--------|
| `approve` | Accept the mapping; `human_review_status → approved` |
| `reject` | Discard the mapping; `human_review_status → rejected` |
| `change-relation` | Keep target; change SKOS predicate |
| `change-target` | Keep relation; select different ontology term |
| `request-evidence` | Defer; `human_review_status → needs_more_evidence` |
| `propose-new-term` | No suitable target; initiate term gap proposal |

### Schema alignment decisions

| Action | Effect |
|--------|--------|
| `approve` | Accept mapping and transformation rule; `human_review_status → approved` |
| `reject` | Discard; `human_review_status → rejected` |
| `change-target` | Keep operation; select different target path |
| `change-operation` | Keep target; select different MappingOperation |
| `request-evidence` | Defer; `human_review_status → needs_more_evidence` |

## Constraints

- No mapping may be auto-approved; all approvals require an explicit user decision.
- The skill does not write back to JSON files in v0.2.0 — decisions are recorded in the review session summary only.
- Ontology review logic must not be applied to schema mapping candidates and vice versa.

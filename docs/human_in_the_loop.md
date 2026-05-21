# Human-in-the-Loop Review Guide

Ontology mapping is a scientific act of interpretation. No algorithm — however sophisticated — can substitute for expert judgement about whether two concepts from different knowledge systems are truly equivalent, closely related, or merely superficially similar. This document explains the human review philosophy embedded in the Ontology Mapping Co-Scientist and how to use it.

---

## Why Human Review is Non-Negotiable

Ontology mappings are not data transformations — they are knowledge alignment claims. A claim that `csv:animal.strain` maps to `mbo:GeneticBackground` with `skos:exactMatch` is a scientific assertion with real consequences:

- It affects downstream data integration, query answering, and federated analysis
- It determines whether data from different institutions can be meaningfully compared
- Errors propagate silently: a wrong mapping may produce results that look plausible but are subtly wrong
- The same source field can map differently depending on context, intent, and scientific domain

The co-scientist treats every machine-generated mapping as a **hypothesis**, not a conclusion. Human review is the mechanism that converts hypotheses into accepted knowledge.

---

## The Review Workflow

```
Source Schema ──► [Automated Pipeline] ──► Mapping Hypotheses
                                                   │
                                        ┌──────────▼──────────┐
                                        │  Review Report (MD)  │
                                        │  + JSON export       │
                                        │  + SSSOM TSV         │
                                        └──────────┬──────────┘
                                                   │
                                        ┌──────────▼──────────┐
                                        │   Human Reviewer(s)  │
                                        │  (domain scientist,  │
                                        │   ontology engineer, │
                                        │   data engineer)     │
                                        └──────────┬──────────┘
                                                   │
                               ┌───────────────────┼───────────────────┐
                               ▼                   ▼                   ▼
                            Approve           Reject / Change    Request more
                                               Predicate          evidence
                               │                   │                   │
                               └───────────────────┴───────────────────┘
                                                   │
                                        ┌──────────▼──────────┐
                                        │  Accepted Mappings   │
                                        │  (with provenance)   │
                                        └─────────────────────┘
```

---

## How to Read the Review Report

Each section of the mapping review report (`*_review_report.md`) covers one source entity. For each entity you will see:

### Top Candidate Mapping
The system's highest-ranked candidate. Check:
- **Predicate**: Is `skos:exactMatch` really appropriate, or is this a `skos:closeMatch`?
- **Confidence**: Numbers above 0.85 are more reliable; below 0.6 requires careful review
- **Evidence**: What specific signals drove this mapping? Are they convincing?
- **Counter-evidence / Warnings**: Red flags raised by the adversarial reviewer

### Alternative Mappings
Up to 3 alternatives. If the top mapping is weak, an alternative may be better. Sometimes the right answer is to combine predicates or create a new term.

### Suggested Human Action
The system suggests one of five actions (see below). This is a starting point, not a directive.

### Warnings
Machine-generated warnings about potential problems. Take these seriously, especially:
- "Possible unit ambiguity" — units are frequently a source of silent errors
- "Strong exactMatch claim" with low confidence — the system may be overconfident
- "No definition on target term" — you are mapping to an insufficiently defined term

---

## Suggested Actions Explained

### `approve`
The system is reasonably confident the mapping is correct. The reviewer should:
1. Verify the predicate is appropriate (exact vs. close vs. broad)
2. Confirm the target term's definition matches the source field's semantics
3. Consider edge cases: does this mapping hold for all valid values?
4. Check for unit compatibility if the field is quantitative

**Approve only when you are willing to stake the integrity of downstream data on it.**

### `reject`
The mapping is wrong or inappropriate. Rejecting a mapping is valuable — it prevents incorrect integrations. Provide a note explaining why.

### `change_predicate`
The target term may be correct, but the relationship type is wrong. Common corrections:
- `skos:exactMatch` → `skos:closeMatch`: the concepts overlap but have different scopes
- `skos:closeMatch` → `skos:broadMatch`: the target is a superclass/broader concept
- Any predicate → `custom:requiresTransform`: the mapping is valid but requires a unit conversion, format change, or vocabulary lookup

### `request_more_evidence`
You are not confident enough to approve or reject. This triggers additional investigation in the next pipeline iteration. Specify what evidence would be convincing:
- A definition that explicitly covers the source field's semantics
- A worked example of the mapping
- Domain expert consultation
- Review of the ontology's formal axioms

### `create_new_ontology_term`
No existing term adequately represents the source entity. This is the most valuable but most expensive action — it initiates an ontology evolution request. Document:
- What the new term should represent
- Where in the hierarchy it should sit
- Proposed label and definition
- Whether it is a class or a property

---

## Quality Criteria for Approving a Mapping

A mapping should only be approved when the reviewer can answer **yes** to all relevant questions:

**Semantic criteria**
- [ ] The target term's definition covers all valid values of the source field
- [ ] The source field's semantics are not broader than the target term
- [ ] The mapping holds across all contexts where the source data may be used
- [ ] The predicate type accurately characterises the relationship

**Practical criteria**
- [ ] Units are compatible (or a unit conversion is specified)
- [ ] Datatypes are compatible (or a transformation is specified as `custom:requiresTransform`)
- [ ] Cardinality is compatible (one-to-one, or acknowledged as one-to-many)
- [ ] The mapping is stable: the target term is not deprecated or likely to change

**Provenance criteria**
- [ ] The evidence is documented in the hypothesis
- [ ] The reviewer's name and date will be recorded
- [ ] The review decision is traceable back to this report

---

## When to Request a New Ontology Term

Request a new term when:

1. The source field represents a real scientific concept that is not modelled in the target ontology
2. The closest existing term is too broad to be useful (`skos:broadMatch` with a large conceptual gap)
3. Multiple source fields from different schemas map to the same ontology term, but they clearly represent different concepts
4. A domain expert confirms that the concept is meaningful and reusable

Do **not** request a new term when:
- The concept is too institution-specific to be useful outside your context
- An existing term is adequate with a `skos:closeMatch` or `custom:requiresTransform`
- You are uncomfortable with the existing term but cannot articulate what is missing

---

## Provenance and Audit Trail

Every mapping hypothesis records:
- `provenance.created_by`: which agent generated the candidate
- `provenance.created_at`: when it was generated
- `provenance.method`: which algorithm was used
- `provenance.pipeline_run_id`: which pipeline run produced it

When a human reviewer acts on a mapping, their decision should be recorded in:
- `human_review_status`: the outcome (approved, rejected, etc.)
- `reviewer_notes`: free-text justification

This audit trail is essential for:
- Reproducing mapping decisions
- Understanding why a mapping was made
- Tracking changes as ontologies evolve
- Supporting regulatory or publication requirements

---

## Multi-Reviewer Recommendations

For high-stakes mappings, consider requiring review from multiple perspectives:

| Reviewer Role | Focuses on |
|---------------|-----------|
| Domain Scientist | Scientific correctness, semantic accuracy |
| Ontology Engineer | Logical consistency, hierarchy, predicate appropriateness |
| Data/API Engineer | Datatype compatibility, units, transformation feasibility |

The co-scientist's agent architecture mirrors this pattern. In future versions, structured review forms for each role will be generated separately.

---

## Handling Uncertainty

Missing information is a first-class output. If you cannot decide:

1. Set status to `needs_more_evidence` — do not force a decision
2. Document specifically what information is missing
3. Flag for follow-up with domain experts
4. Note whether the mapping is blocking a data integration deadline (urgency affects acceptable uncertainty)

**It is better to have an unresolved mapping with documented uncertainty than a confidently wrong mapping with no uncertainty expressed.**

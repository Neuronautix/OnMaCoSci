# Human Review Policy

## Purpose

This document defines the mandatory human review requirements for the mapping co-scientist plugin. It exists to prevent silent errors, over-confident automatic approvals, and inappropriate semantic assertions from reaching downstream consumers.

---

## Principle 1: No auto-approval

**All mapping approvals require an explicit human decision.**

The plugin may present recommendations, highlight low-risk candidates, and group items for efficiency — but it may never mark a mapping as `approved` on behalf of the user. This applies without exception, including:

- High-confidence mappings (confidence = 1.00)
- Mappings with zero adversarial flags
- Trivially obvious field renames (e.g., `mouse_id` → `animal.id`)
- Constant assignments inferred from column name conventions

Rationale: The pipeline is a hypothesis generator. Hypotheses are not facts. Every downstream use of a mapping (ontology publication, data transformation, federated query) depends on a human having verified the mapping is correct for their specific use case.

---

## Principle 2: SKOS exactMatch requires semantic sign-off

**`skos:exactMatch` must never be assigned without domain expert confirmation.**

`skos:exactMatch` is a strong semantic assertion meaning the two concepts are interchangeable in any context. This requires:

1. A human reviewer with domain expertise (not just ontology engineering familiarity) to confirm the assertion
2. A documented rationale in the review notes (not just "lexical match = 1.00")
3. An explicit approval decision by the reviewer, not inherited from a previous review session

The pipeline generator is hardcoded to assign `skos:closeMatch` as the maximum for high lexical similarity. If `skos:exactMatch` appears in pipeline output without a human review note, treat it as a data error.

---

## Principle 3: Information loss must be acknowledged

**No lossy mapping may be approved without explicit acknowledgement.**

For schema alignment, any hypothesis where `information_loss: true` requires:

1. The reviewer to read the `information_loss_description` field
2. The reviewer to state whether the loss is acceptable for the intended use case
3. An explicit approval decision that includes a note confirming awareness of the loss

Silent approval of a lossy mapping is not permitted, even if the confidence score is high.

---

## Principle 4: Type safety for operations

**The assigned MappingOperation must be appropriate for the source and target datatypes.**

| Situation | Required operation |
|-----------|------------------|
| Source: integer, Target: string | DATATYPE_CONVERSION (not DIRECT_COPY) |
| Source: number with unit, Target: number with different unit | UNIT_CONVERSION |
| Source: enum string, Target: different enum string | ENUMERATION_REMAPPING |
| Source: flat field, Target: nested JSON path | NESTED_PATH |

If a DIRECT_COPY or RENAME operation is assigned for incompatible types, it must be corrected before the mapping can be approved.

---

## Principle 5: Ambiguous fields must be clarified before approval

**Fields with ambiguous semantics must be clarified by the user before a mapping is approved.**

Fields in this category include (but are not limited to):
- `ActivityCount` — could be raw sensor count, derived index, or normalised score
- `Index`, `Score`, `Rank` — same ambiguity
- Any field where the top-2 candidates have confidence within 0.05 of each other

Before approving, the reviewer must confirm:
1. What the field represents in the source system
2. That the target path is appropriate for that interpretation

---

## Principle 6: Run type boundaries

**Ontology alignment review logic must not be applied to schema mapping candidates, and vice versa.**

The two pipeline types produce different hypothesis models:

| Pipeline | Hypothesis model | Relations |
|---------|-----------------|-----------|
| ontology-align | `OntologyMappingHypothesis` | SKOS predicates (`skos:exactMatch`, etc.) |
| schema-align | `FieldMappingHypothesis` | `MappingOperation` values (`direct_copy`, `nested_path`, etc.) |

Applying SKOS logic to a schema mapping candidate (or suggesting SKOS relations for field mappings) is a category error and produces misleading output.

---

## Principle 7: Do not fabricate validation results

**Plugin commands must not claim to have run validation unless they actually invoked the CLI.**

If a command instructs the user to run the pipeline or a validation step, it must:
1. Actually execute the command via a Bash tool call
2. Report the actual exit code and stderr verbatim
3. Not paraphrase, summarise, or improve the output before reporting

Claiming "validation passed" without running the command is prohibited, even if a prior run produced passing output.

---

## Exceptions

The following are NOT prohibited but must be explicitly documented:

| Exception | Requirement |
|-----------|------------|
| Bulk-presenting Tier 3 items for efficient review | User must explicitly request batch mode; each item still requires individual confirmation |
| Exporting with `--force` despite unreviewed items | User must type "yes" to confirm; the export summary must list all skipped checks |
| Re-using a previous review session's decisions | The session context must be explicitly re-established; stale decisions from a different run must not be applied |

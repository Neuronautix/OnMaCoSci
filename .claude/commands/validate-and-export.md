# /validate-and-export

Re-run validation checks against an existing pipeline output directory and, if all required approvals are in place, produce the final export artefacts. Works for both ontology alignment and schema alignment runs.

## Usage

```
/validate-and-export <output-dir> [--allow-warnings] [--force]
```

| Flag | Meaning |
|------|---------|
| `--allow-warnings` | Proceed to export even if validation produces `warning` status items (but not `failed`) |
| `--force` | Export even if some items are still `awaiting_review` (user must confirm intent) |

If the user omits the output directory, ask them to supply one.

## What this command does

### Step 1 — Read current state

Call:
```bash
python scripts/read_run_summary.py <output-dir>
```

Parse the summary and report:
- Total hypotheses
- Breakdown by `human_review_status` (awaiting_review / approved / rejected / needs_more_evidence)
- Breakdown by `validation_status` (passed / warning / failed / pending)
- Whether the run is an ontology or schema alignment

### Step 2 — Pre-export checklist

Before proceeding, verify:

**For ontology alignment runs:**
- [ ] No hypothesis has `validation_status: failed`
- [ ] No hypothesis has `human_review_status: awaiting_review` (unless `--force` is set)
- [ ] No `skos:exactMatch` relation exists in any hypothesis without an explicit human approval note confirming semantic equivalence was verified by a domain expert
- [ ] All pipeline adversarial flags with `severity: high` have been reviewed
- [ ] The three-agent debate's cross-mapping consistency report has been reviewed and all collisions resolved

**For schema alignment runs:**
- [ ] No hypothesis has `validation_status: failed`
- [ ] No hypothesis has `human_review_status: awaiting_review` (unless `--force` is set)
- [ ] All `information_loss: true` hypotheses have an explicit human approval decision
- [ ] All datatype mismatches in approved mappings use the correct MappingOperation (DATATYPE_CONVERSION, not DIRECT_COPY)
- [ ] All collisions identified in the mediator's cross-mapping consistency report have been resolved
- [ ] Unit companion constant assignments are present for all unit-bearing source fields

If any checklist item fails and `--force` is not set, **stop here** and report what blocks export. Do NOT proceed.

If `--force` is set and there are `awaiting_review` items, ask the user to confirm with a typed "yes" before continuing. State how many items will be exported without human review.

### Step 3 — Re-run validation (ontology runs only)

For ontology alignment, the pipeline validation agent checks SKOS predicate appropriateness for source/target type pairs, OWL hierarchy compatibility, and domain/range compatibility.

Note: SHACL validation is not wired in v0.2.0. State this explicitly.

### Step 4 — Export artefacts

**Ontology alignment export** — re-run the full pipeline to regenerate all artefacts:
```bash
python -m mapping_co_scientist.ontology_align.cli \
  --source <original-source-csv> \
  --ontology <original-ontology-profile> \
  --output-dir <output-dir> \
  --verbose
```

Report all output files:
- `ontology_mapping_candidates.json`
- `ontology_mapping_candidates.sssom.tsv`
- `ontology_review_report.md`
- `term_gap_proposals.json`

**Schema alignment export** — re-run the full pipeline:
```bash
python -m mapping_co_scientist.schema_align.cli \
  --source <original-source-csv> \
  --target-schema <original-target-schema> \
  --output-dir <output-dir> \
  --verbose
```

Report all output files:
- `field_mapping_candidates.json`
- `approved_mapping_spec.yaml`
- `transformation_rules.json`
- `transformation_validation_report.md`
- `unmapped_fields_report.md`
- `information_loss_report.json`

### Step 5 — Post-export summary

```markdown
## Export Complete

**Run type**: ontology-align | schema-align
**Output directory**: `<output-dir>`
**Exported at**: <timestamp>

### Artefacts

| File | Status |
|------|--------|
| <filename> | generated |
...

### Mapping Quality

- **Approved mappings**: N
- **Rejected mappings**: N
- **Mappings with warnings**: N
- **Unmapped source fields**: N (schema runs)
- **Term gap proposals**: N (ontology runs)

### SSSOM check (ontology runs only)

Verify no skos:exactMatch appears without human sign-off:
```bash
grep "skos:exactMatch" <output-dir>/ontology_mapping_candidates.sssom.tsv
```
If any exactMatch rows appear, review them individually before sharing the SSSOM file.
```

### Checklist items skipped (if --force was used)

List all skipped checks and how many items were exported without human review.

## Critical constraints

- NEVER export a schema alignment run as SSSOM. Schema-align outputs YAML and JSON specs only.
- NEVER claim validation passed unless you actually ran the command and read its output.
- NEVER skip the pre-export checklist, even if the user says "just export it."
- If `--force` is used, document in the summary which checks were skipped.
- This command does NOT persist human review decisions back to JSON (review ledger planned for v0.3.0).

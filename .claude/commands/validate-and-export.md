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
- [ ] No `skos:exactMatch` relation exists in any approved hypothesis without a corresponding human approval note confirming semantic equivalence
- [ ] All `high`-severity adversarial flags have been reviewed

**For schema alignment runs:**
- [ ] No hypothesis has `validation_status: failed`
- [ ] No hypothesis has `human_review_status: awaiting_review` (unless `--force` is set)
- [ ] All `information_loss: true` hypotheses have an explicit human approval decision
- [ ] All datatype mismatches in approved mappings have the correct operation (DATATYPE_CONVERSION, not DIRECT_COPY)

If any checklist item fails and `--force` is not set, **stop here** and report what blocks export. Do NOT proceed to export.

If `--force` is set and there are `awaiting_review` items, ask the user to confirm with a typed "yes" before continuing. State how many items will be exported without human review.

### Step 3 — Re-run validation (ontology runs only)

For ontology alignment, the pipeline validation agent checks:
- SKOS predicate appropriateness for source/target type pair
- OWL hierarchy compatibility (subClassOf, equivalentClass)
- Domain/range compatibility

At present, SHACL validation is not wired in (v0.2.0 limitation). State this explicitly.

### Step 4 — Export artefacts

**Ontology alignment export:**

The pipeline already produced these files during the original run. To regenerate them with current hypothesis state, re-run the full pipeline or use the exporter module directly:
```bash
python -m mapping_co_scientist.ontology_align.cli \
  --source <original-source-csv> \
  --ontology <original-ontology-profile> \
  --output-dir <output-dir> \
  --verbose
```

Report the paths of all output files:
- `ontology_mapping_candidates.json`
- `ontology_mapping_candidates.sssom.tsv`
- `ontology_review_report.md`
- `term_gap_proposals.json`

**Schema alignment export:**

```bash
python -m mapping_co_scientist.schema_align.cli \
  --source <original-source-csv> \
  --target-schema <original-target-schema> \
  --output-dir <output-dir> \
  --verbose
```

Report the paths of all output files:
- `field_mapping_candidates.json`
- `approved_mapping_spec.yaml`
- `transformation_rules.json`
- `transformation_validation_report.md`
- `unmapped_fields_report.md`
- `information_loss_report.json`

### Step 5 — Post-export summary

After export:

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

### SSSOM note

(Ontology runs only) The `.sssom.tsv` file uses SKOS predicates. No `skos:exactMatch` should appear unless a human reviewer explicitly upgraded a mapping from closeMatch. Verify:
```bash
grep "skos:exactMatch" <output-dir>/ontology_mapping_candidates.sssom.tsv
```
If any exactMatch rows appear, review them individually before sharing the SSSOM file.
```

## Critical constraints

- NEVER export a schema alignment run as SSSOM. Schema-align outputs YAML and JSON specs only.
- NEVER claim validation passed unless you actually ran the validation command and read its output.
- NEVER skip the pre-export checklist, even if the user says "just export it."
- If the user bypasses checks using `--force`, document in the summary which checks were skipped.
- This command does NOT write human review decisions back to the JSON. That requires the review ledger (planned for v0.3.0).

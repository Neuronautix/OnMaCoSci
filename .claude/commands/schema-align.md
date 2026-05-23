# /schema-align

Run the schema alignment pipeline against a source CSV and a target JSON Schema, then run the three-agent debate protocol to produce evidence-weighted ranked candidates for human review.

## Usage

```
/schema-align --source <path/to/source.csv> --target-schema <path/to/schema.json> [--output-dir <dir>] [--run-id <id>]
```

If the user omits arguments, ask them to supply:
1. Path to the source CSV (columns = source field names)
2. Path to the target JSON Schema
3. (Optional) Output directory (default: `examples/schema_align/outputs`)

## What this command does

### Step 1 — Execute the pipeline

Run:
```bash
python -m mapping_co_scientist.schema_align.cli \
  --source <source-csv> \
  --target-schema <target-schema> \
  --output-dir <output-dir> \
  --verbose
```

Report the exit code and any stderr output verbatim. Do NOT suppress errors or fabricate a success message if the command fails.

### Step 2 — Read the run summary

After a successful run, call:
```bash
python scripts/read_run_summary.py <output-dir>
```

Present the full Markdown output. This shows all candidate hypotheses grouped by source field, with the top-1 mapping, alternatives, datatype information, information loss flags, and current `human_review_status`.

### Step 3 — Run the three-agent debate

Load the three agent definitions:
- `claude-plugin/agents/source-schema-advocate.md` — speaks for the source CSV fields (source system data engineer)
- `claude-plugin/agents/target-schema-advocate.md` — speaks for the target JSON Schema fields (target system data engineer)
- `claude-plugin/agents/mapping-mediator.md` — runs the debate, computes LR scores, produces ranked output

For each source field in the run summary, run the full Structured Evidence Debate (SED) protocol as defined in `mapping-mediator.md`:

1. **Round 0** (mediator): inject pipeline context (confidence, rank, adversarial flags, information loss, warnings, evidence lists)
2. **Round 1** (both advocates independently): each produces 1–3 arguments using the FOR/AGAINST/evidence-type/confidence/counterpoint-weakness structure
3. **Round 2** (advocates see each other's Round 1): each may produce 0–2 rebuttals
4. **Scoring** (mediator): compute Elo ratings using pairwise argument-weighted updates; apply flat Elo penalties for blocking conditions; re-rank candidates by final Elo; identify rank inversions

After all per-field debates, the mediator runs the **Cross-Mapping Consistency Report** (collision detection, unit companion gap analysis, confidence cliff analysis, coverage by field type).

### Step 4 — Present mediator output

Present the full mediator output:
- Per-field debate summaries with argument logs and score computation tables
- Cross-mapping consistency report including unit companion gaps
- Prioritised review queue (Tier 1 / Tier 2 / Tier 3)

### Step 5 — Guide human review

Work through the review queue in tier order. For each field, present the mediator's recommended action and ask the user to choose one of:

| Action | What it means |
|--------|---------------|
| `approve` | Accept the debate top-1 mapping and its transformation rule |
| `reject` | Discard this mapping; leave field unmapped |
| `change-target` | Keep operation, change target path (ask which one) |
| `change-operation` | Keep target, change MappingOperation (ask which one) |
| `request-evidence` | Mark `needs_more_evidence`; defer |

For constant assignments (no source field):
| Action | What it means |
|--------|---------------|
| `approve` | Accept the constant value |
| `change-value` | Use a different constant value |
| `reject` | Remove this constant assignment |

For any mapping where `information_loss: true`, before accepting `approve`:
1. Quote the `information_loss_description` to the user
2. Ask explicitly: "Do you accept this information loss? (yes/no)"
3. Only proceed to approve if the user says yes; record the acknowledgement in notes

Do NOT auto-approve any mapping.

### Step 6 — Decision summary and coverage

After all items are reviewed:

```markdown
## Review Decisions — <run-id>

| Source Field | Target Path | Operation | Decision | Notes |
|---|---|---|---|---|
| Weight_g | measurements.bodyWeight.value | nested_path | approved | |
| measurements.bodyWeight.unit | "g" | constant_assignment | approved | inferred from _g suffix |
| ActivityCount | — | — | rejected | ambiguous; needs clarification |
...

## Coverage
- Fields approved: N
- Fields rejected: N
- Fields deferred: N
- Unmapped: N
- Lossy mappings acknowledged: [list]
```

## Critical constraints

- NEVER claim the pipeline validated a file you did not actually run.
- NEVER produce an SSSOM file — schema-align outputs YAML and JSON specs, not SSSOM TSV.
- NEVER use SKOS predicates to describe schema field mappings. Schema mappings use MappingOperation values.
- NEVER auto-approve any mapping on behalf of the user.
- NEVER approve a lossy mapping without the user explicitly acknowledging the information loss.
- This command covers **schema field mapping only**. For ontology term alignment use `/ontology-align`.

## Outputs produced by the pipeline

| File | Description |
|------|-------------|
| `field_mapping_candidates.json` | All FieldMappingHypothesis objects |
| `approved_mapping_spec.yaml` | YAML mapping specification |
| `transformation_rules.json` | TransformationRule objects (JSON) |
| `transformation_validation_report.md` | Human review report with adversarial flags |
| `unmapped_fields_report.md` | Source fields with no suitable target |
| `information_loss_report.json` | Structured lossiness analysis |

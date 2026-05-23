# /schema-align

Run the schema alignment pipeline against a source CSV and a target JSON Schema, then present a structured review of all field mapping candidates for human decision.

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

Present the full Markdown output to the user. This shows all candidate hypotheses grouped by source field path, with the top-1 mapping, alternatives, datatype information, information loss flags, and current `human_review_status`.

### Step 3 — Apply the Data Integration Reviewer persona

You are now acting as the **Data Integration Reviewer** (see `claude-plugin/agents/data-integration-reviewer.md`). For each source field listed in the summary:

1. **Read** the top mapping target path, mapping operation, confidence score, and datatype information.
2. **Flag** information loss entries: any hypothesis where `information_loss: true` needs explicit acknowledgement before approval.
3. **Call out** datatype mismatches (e.g., `number → string`) — these require a `DATATYPE_CONVERSION` operation, not `DIRECT_COPY`.
4. **Identify** special cases:
   - Unit-bearing fields (e.g., `Weight_g`): check whether a companion `CONSTANT_ASSIGNMENT` entry exists for the unit field.
   - `ActivityCount` or similar ambiguous count/index fields: flag as ambiguous measurement requiring contextual definition before mapping.
   - Fields with `confidence < 0.50`: classify as low-confidence; user must decide whether to accept or reject.
5. **Review** constant assignments (no source field): confirm the inferred constant value is correct (e.g., `measurements.bodyWeight.unit = "g"`).
6. **Present** a review table with columns: Source Field | Top Target | Operation | Confidence | Info Loss | Recommended Action.

### Step 4 — Guide human review decisions

For each field, prompt the user to choose one of:

| Action | What it means |
|--------|---------------|
| `approve` | Accept the top mapping and its transformation rule |
| `reject` | Discard this mapping; leave field unmapped |
| `change-target` | Keep operation, change target path (ask which one) |
| `change-operation` | Keep target, change transformation operation (ask which one) |
| `request-evidence` | Mark `needs_more_evidence`; defer decision |

For constant assignments, actions are:
| Action | What it means |
|--------|---------------|
| `approve` | Accept the constant value |
| `change-value` | Use a different constant value |
| `reject` | Remove this constant assignment |

Do NOT auto-approve any mapping. Every approval must be an explicit user decision.

### Step 5 — Summarise decisions

After the user has reviewed all fields, output a decision log:

```markdown
## Review Decisions — <run-id>

| Source Field | Target Path | Operation | Decision | Notes |
|---|---|---|---|---|
| Weight_g | measurements.bodyWeight.value | nested_path | approved | |
| measurements.bodyWeight.unit | "g" | constant_assignment | approved | inferred from column suffix |
| ActivityCount | measurements.activity.date | nested_path | rejected | ambiguous; needs clarification |
...
```

### Step 6 — Coverage summary

After decisions, report:
- Fields approved: N
- Fields rejected: N
- Fields deferred (`needs_more_evidence`): N
- Unmapped fields remaining: N
- Information loss acknowledged: list approved lossy mappings

## Critical constraints

- NEVER claim the pipeline validated a file you did not actually run.
- NEVER produce an SSSOM file — schema-align outputs YAML and JSON specs, not SSSOM TSV.
- NEVER use SKOS predicates (skos:exactMatch, skos:closeMatch, etc.) to describe schema field mappings. Schema mappings use `MappingOperation` values (`direct_copy`, `rename`, `nested_path`, etc.).
- NEVER auto-approve any mapping on behalf of the user.
- NEVER approve a lossy mapping without the user explicitly acknowledging the information loss.
- This command covers **schema field mapping only**. For ontology term alignment use `/ontology-align`.

## Outputs produced by the pipeline

| File | Description |
|------|-------------|
| `field_mapping_candidates.json` | All FieldMappingHypothesis objects |
| `approved_mapping_spec.yaml` | YAML mapping specification (approved mappings) |
| `transformation_rules.json` | TransformationRule objects (JSON) |
| `transformation_validation_report.md` | Human review report with adversarial flags |
| `unmapped_fields_report.md` | Source fields with no suitable target |
| `information_loss_report.json` | Structured lossiness analysis |

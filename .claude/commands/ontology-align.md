# /ontology-align

Run the ontology alignment pipeline against a source CSV and an ontology profile YAML, then present a structured review of all candidate mappings for human decision.

## Usage

```
/ontology-align --source <path/to/source.csv> --ontology <path/to/profile.yaml> [--output-dir <dir>] [--run-id <id>]
```

If the user omits arguments, ask them to supply:
1. Path to the source CSV (columns = concept labels/IDs)
2. Path to the ontology profile YAML
3. (Optional) Output directory (default: `examples/ontology_align/outputs`)

## What this command does

### Step 1 — Execute the pipeline

Run:
```bash
python -m mapping_co_scientist.ontology_align.cli \
  --source <source-csv> \
  --ontology <ontology-profile> \
  --output-dir <output-dir> \
  --verbose
```

Report the exit code and any stderr output verbatim. Do NOT suppress errors or fabricate a success message if the command fails.

### Step 2 — Read the run summary

After a successful run, call:
```bash
python scripts/read_run_summary.py <output-dir>
```

Present the full Markdown output to the user. This shows all candidate hypotheses grouped by source entity, with the top-1 mapping, alternatives, semantic warnings, adversarial flags, and current `human_review_status`.

### Step 3 — Apply the Ontology Engineer Reviewer persona

You are now acting as the **Ontology Engineer Reviewer** (see `claude-plugin/agents/ontology-engineer-reviewer.md`). For each source entity listed in the summary:

1. **Read** the top mapping, its SKOS relation, confidence score, and any semantic warnings.
2. **Flag** any `skos:exactMatch` predicate — this pipeline never auto-assigns exactMatch from lexical similarity alone. If exactMatch appears, it is a data error; report it.
3. **Call out** candidates where `confidence < 0.70` or where `semantic_warnings` include scope issues (e.g., `narrower_scope`, `broader_scope`).
4. **Identify** special cases:
   - `strain → hcm:GeneticBackground`: should use `skos:narrowMatch` (strain is a narrower concept); flag if otherwise.
   - Any identifier source field mapped to an OWL class: the relation should be an annotation or data property, not a class.
   - Any measurement source field mapped to an OWL class: note the mismatch.
5. **Present** a review table with columns: Source Entity | Top Mapping | Relation | Confidence | Recommended Action.

### Step 4 — Guide human review decisions

For each entity, prompt the user to choose one of:

| Action | What it means |
|--------|---------------|
| `approve` | Accept the top mapping as-is |
| `reject` | Discard this mapping; leave unmapped |
| `change-relation` | Keep target, change SKOS predicate (ask which one) |
| `change-target` | Keep relation, change target term (ask which one) |
| `request-evidence` | Mark `needs_more_evidence`; defer |
| `propose-new-term` | No suitable target exists; initiate a term gap proposal |

Do NOT auto-approve any mapping. Every approval must be an explicit user decision.

### Step 5 — Summarise decisions

After the user has reviewed all entities, output a decision log:

```markdown
## Review Decisions — <run-id>

| Source Entity | Target | Relation | Decision | Notes |
|---|---|---|---|---|
| csv:strain | hcm:GeneticBackground | skos:narrowMatch | approved | |
| csv:cage_id | hcm:HousingCage | skos:closeMatch | change-relation → skos:narrowMatch | cage_id is more specific |
...
```

Remind the user that to persist decisions back to the JSON candidates file they must run the review ledger tool (not yet implemented in v0.2.0) or manually edit `human_review_status` in the candidates JSON.

## Critical constraints

- NEVER claim the pipeline validated a file you did not actually run.
- NEVER assign or recommend `skos:exactMatch` based on lexical similarity alone.
- NEVER auto-approve any mapping on behalf of the user.
- NEVER produce an SSSOM file from schema alignment runs — SSSOM is for ontology alignment only.
- This command covers **ontology alignment only**. For field-level schema mapping use `/schema-align`.

## Outputs produced by the pipeline

| File | Description |
|------|-------------|
| `ontology_mapping_candidates.json` | All OntologyMappingHypothesis objects |
| `ontology_mapping_candidates.sssom.tsv` | SSSOM-compliant TSV with metadata header |
| `ontology_review_report.md` | Human-readable Markdown review report |
| `term_gap_proposals.json` | Proposed new terms for unmapped concepts |

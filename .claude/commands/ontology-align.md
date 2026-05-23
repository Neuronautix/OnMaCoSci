# /ontology-align

Run the ontology alignment pipeline against a source CSV and an ontology profile YAML, then run the three-agent debate protocol to produce evidence-weighted ranked candidates for human review.

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

Present the full Markdown output. This shows all candidate hypotheses grouped by source entity with the top-1 mapping, alternatives, semantic warnings, adversarial flags, and current `human_review_status`.

### Step 3 — Run the three-agent debate

Load the three agent definitions:
- `claude-plugin/agents/source-schema-advocate.md` — speaks for the source CSV concepts
- `claude-plugin/agents/target-schema-advocate.md` — speaks for the ontology terms (ontology engineer role)
- `claude-plugin/agents/mapping-mediator.md` — runs the debate, computes LR scores, produces ranked output

For each source entity in the run summary, run the full Structured Evidence Debate (SED) protocol as defined in `mapping-mediator.md`:

1. **Round 0** (mediator): inject pipeline context (confidence, rank, adversarial flags, semantic warnings, evidence lists)
2. **Round 1** (both advocates independently): each produces 1–3 arguments using the FOR/AGAINST/evidence-type/confidence/counterpoint-weakness structure
3. **Round 2** (advocates see each other's Round 1): each may produce 0–2 rebuttals
4. **Scoring** (mediator): compute `debate_score` using the LR formula; re-rank candidates; identify rank inversions

After all per-entity debates, the mediator runs the **Cross-Mapping Consistency Report** (collision detection, SKOS symmetry violations, confidence cliff analysis, coverage by entity type).

### Step 4 — Present mediator output

Present the full mediator output:
- Per-entity debate summaries with argument logs and score computation tables
- Cross-mapping consistency report
- Prioritised review queue (Tier 1 / Tier 2 / Tier 3)

### Step 5 — Guide human review

Work through the review queue in tier order. For each entity, present the mediator's recommended action and ask the user to choose one of:

| Action | What it means |
|--------|---------------|
| `approve` | Accept the debate top-1 mapping |
| `reject` | Discard this mapping; leave unmapped |
| `change-relation` | Keep target, change SKOS predicate (ask which one) |
| `change-target` | Keep relation, change target term (ask which one) |
| `request-evidence` | Mark `needs_more_evidence`; defer |
| `propose-new-term` | No suitable target; initiate a term gap proposal |

Do NOT auto-approve any mapping. Every approval must be an explicit user decision.

### Step 6 — Decision summary

After all items are reviewed:

```markdown
## Review Decisions — <run-id>

| Source Entity | Debate Top-1 | Relation | Decision | Notes |
|---|---|---|---|---|
| csv:strain | hcm:GeneticBackground | skos:narrowMatch | approved | |
...
```

Remind the user that decisions must be manually persisted to the candidates JSON until the review ledger is available in v0.3.0.

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

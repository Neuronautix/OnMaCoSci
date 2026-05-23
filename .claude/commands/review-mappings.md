# /review-mappings

Open an existing pipeline output directory and guide the user through reviewing all pending mapping candidates. Works for both ontology alignment and schema alignment outputs.

## Usage

```
/review-mappings <output-dir> [--persona <ontology-engineer|data-integration|adversarial|meta>]
```

If the user omits the output directory, ask them to supply one. If `--persona` is omitted, auto-detect based on run type (ontology-align → ontology-engineer, schema-align → data-integration).

## What this command does

### Step 1 — Detect run type

Check which candidates file exists:
- `<output-dir>/ontology_mapping_candidates.json` → ontology alignment run
- `<output-dir>/field_mapping_candidates.json` → schema alignment run

If neither exists, report the error and list what files are present:
```bash
ls <output-dir>/
```

### Step 2 — Read the run summary

Call:
```bash
python scripts/read_run_summary.py <output-dir>
```

Present the structured Markdown summary. Identify:
- Total items awaiting review (`human_review_status: awaiting_review`)
- Items already reviewed (approved / rejected / needs_more_evidence)
- Items with high-severity adversarial flags
- Items with information loss (schema runs)
- Term gap proposals (ontology runs)

### Step 3 — Apply the selected persona

**Ontology Engineer Reviewer** (default for ontology runs):
- Focus: SKOS relation correctness, scope analysis, hierarchy compatibility, OWL axiom safety
- Red flags: `skos:exactMatch` from lexical match alone, identifier-to-class mismatches, owl:equivalentClass proposals without domain expert sign-off
- See full persona: `claude-plugin/agents/ontology-engineer-reviewer.md`

**Data Integration Reviewer** (default for schema runs):
- Focus: transformation operation correctness, datatype compatibility, unit handling, information loss acknowledgement
- Red flags: DIRECT_COPY across incompatible types, missing unit constant assignments, unmapped fields silently dropped
- See full persona: `claude-plugin/agents/data-integration-reviewer.md`

**Adversarial Reviewer** (any run, explicit `--persona adversarial`):
- Focus: actively challenge every top-1 mapping; look for subtle errors the generator may have missed
- Questions: "Is this the best available target, or just the closest lexical match?", "Does the confidence score reflect genuine semantic similarity?"
- See full persona: `claude-plugin/agents/adversarial-reviewer.md`

**Meta Reviewer** (any run, explicit `--persona meta`):
- Focus: cross-cutting consistency across all mappings in a single run
- Questions: "Are structurally similar source fields mapped consistently?", "Do any pairs of mappings create circular or contradictory assertions?"
- See full persona: `claude-plugin/agents/meta-reviewer.md`

### Step 4 — Prioritised review queue

Sort items into three tiers:

**Tier 1 — Needs immediate decision** (present these first):
- `human_review_status: awaiting_review` AND adversarial severity `high`
- `human_review_status: awaiting_review` AND `information_loss: true`
- `human_review_status: awaiting_review` AND `confidence < 0.50`

**Tier 2 — Standard review**:
- `human_review_status: awaiting_review` AND adversarial severity `medium`

**Tier 3 — Low-risk approval candidates**:
- `human_review_status: awaiting_review` AND adversarial severity `clean` or `low`
- `confidence >= 0.85`

Present Tier 1 items one at a time and ask for an explicit decision before moving to Tier 2. Tier 3 items may be batch-presented for bulk approval, but ONLY after the user explicitly confirms they want bulk review.

### Step 5 — Collect decisions

For each item, record:
- The user's decision (approve / reject / change-relation / change-target / change-operation / request-evidence / propose-new-term)
- Any notes the user adds
- The timestamp of the decision

### Step 6 — Decision summary

After completing the review queue, output:

```markdown
## Review Session Summary

**Output directory**: `<output-dir>`
**Run type**: ontology-align | schema-align
**Persona used**: <persona>
**Items reviewed this session**: N

### Decisions Made

| ID | Source | Target | Decision | Notes |
|----|--------|--------|----------|-------|
...

### Remaining Items

- **Awaiting review**: N
- **Deferred (needs_more_evidence)**: N

### Suggested Next Steps

- [ ] Persist decisions to candidates JSON (run review ledger when available in v0.3.0)
- [ ] Re-run validation for changed mappings: `/validate-and-export <output-dir>`
- [ ] Address term gap proposals (ontology runs)
- [ ] Investigate deferred items with domain expert
```

## Critical constraints

- NEVER auto-approve any item, including low-risk Tier 3 items.
- NEVER claim a validation was performed unless you actually ran the CLI command.
- NEVER modify hypothesis JSON files directly — inform the user that persistence requires the review ledger (not yet available in v0.2.0).
- NEVER apply ontology reviewer logic to schema alignment items or vice versa.

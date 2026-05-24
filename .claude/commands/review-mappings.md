# /review-mappings

Open an existing pipeline output directory, run the three-agent debate protocol across all pending candidates, and guide the user through the prioritised review queue. Works for both ontology alignment and schema alignment outputs.

## Usage

```
/review-mappings <output-dir>
```

If the user omits the output directory, ask them to supply one.

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

Present the structured Markdown summary. Identify at a glance:
- Total items awaiting review (`human_review_status: awaiting_review`)
- Items already reviewed (approved / rejected / needs_more_evidence)
- Items with high-severity pipeline adversarial flags
- Items with information loss (schema runs)
- Term gap proposals (ontology runs)

### Step 3 — Run the three-agent debate

Load all three agent definitions:
- `claude-plugin/agents/source-schema-advocate.md`
- `claude-plugin/agents/target-schema-advocate.md`
- `claude-plugin/agents/mapping-mediator.md`

The debate roles adapt to the run type automatically:

| Run type | Source advocate role | Target advocate role |
|----------|---------------------|---------------------|
| ontology-align | Field scientist who collected source CSV data | Ontology engineer who knows the OWL/SKOS ontology |
| schema-align | Source system data engineer | Target schema data engineer |

For **every source entity/field** with `human_review_status: awaiting_review`, run the full Structured Evidence Debate (SED) protocol:

1. **Round 0** (mediator, silent): load pipeline context — confidence, rank, adversarial flags, semantic warnings / information loss, evidence lists
2. **Round 1**: both advocates produce 1–3 independent arguments (FOR or AGAINST each top-k candidate)
3. **Round 2**: advocates see each other's Round 1; each may produce 0–2 rebuttals
4. **Scoring**: mediator computes Elo ratings via pairwise K-weighted updates per argument, applies flat Elo penalties for blocking conditions, re-ranks by final Elo, identifies rank inversions

After all per-entity debates, the mediator produces a **Cross-Mapping Consistency Report** covering:
- Target path/term collisions
- SKOS symmetry violations (ontology runs)
- Rank inversions
- Ambiguous top-1 selections (Elo gap top-1 vs top-2 < 50)
- Strong isolations (delta > 0.30)
- Coverage by entity/field type
- Unit companion gaps (schema runs)

### Step 4 — Present mediator output

Present:
1. The cross-mapping consistency report (so the user sees the whole-run picture first)
2. The prioritised review queue sorted into Tier 1, Tier 2, Tier 3

### Step 5 — Work through the review queue

**Tier 1** — present one at a time, require explicit decision before advancing:
- Pipeline adversarial severity `high`
- `information_loss == true` with no rebuttal from source advocate
- final Elo < 1250
- Rank inversion occurred
- `skos:exactMatch` present (ontology runs)

**Tier 2** — present in sequence:
- Pipeline adversarial severity `medium`
- final Elo between 1250 and 1500

**Tier 3** — may be batch-presented **only** with explicit user consent:
- No blocking concerns; final Elo ≥ 1500; advocates in agreement

For each item, present the mediator's recommendation and ask the user to choose an action.

**Ontology alignment decisions:**
| approve | reject | change-relation | change-target | request-evidence | propose-new-term |

**Schema alignment decisions:**
| approve | reject | change-target | change-operation | request-evidence |

**Constant assignment decisions:**
| approve | change-value | reject |

For any `information_loss: true` mapping, require explicit acknowledgement before `approve`.

### Step 6 — Session summary

After completing the review queue (or when the user stops):

```markdown
## Review Session Summary

**Output directory**: `<output-dir>`
**Run type**: ontology-align | schema-align
**Items debated**: N
**Items reviewed this session**: N

### Decisions Made

| Source | Debate Top-1 | Decision | Notes |
|---|---|---|---|
...

### Remaining Items

- **Awaiting review**: N
- **Deferred (needs_more_evidence)**: N

### Consistency Issues Requiring Follow-up

(list any unresolved collisions, symmetry violations, or rank inversions)

### Next Steps

- [ ] Persist decisions to candidates JSON (review ledger available in v0.3.0)
- [ ] Re-run for changed mappings: `/validate-and-export <output-dir>`
- [ ] Investigate deferred items with domain expert
- [ ] Address term gap proposals (ontology runs)
```

## Critical constraints

- NEVER auto-approve any item, including low-risk Tier 3 items without explicit user decision per item.
- NEVER claim a validation was performed unless you actually ran the CLI command.
- NEVER modify hypothesis JSON files — decisions are recorded in session summary only until v0.3.0.
- NEVER apply ontology debate logic to schema alignment candidates or vice versa.

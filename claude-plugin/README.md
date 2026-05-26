# Mapping Co-Scientist — Claude Code Plugin

This directory contains the Claude Code plugin scaffold for the `mapping-co-scientist` package. It provides four slash commands, a three-agent debate system, three skill definitions, and two reference documents for working with ontology alignment and schema field mapping pipelines.

## Quick start

1. Open this repository in Claude Code (CLI or IDE extension).
2. `CLAUDE.md` at the repository root provides project context automatically.
3. Run `/ontology-align` or `/schema-align` to start a pipeline and review session.

## Commands

| Command | Description |
|---------|-------------|
| `/ontology-align` | Run ontology alignment pipeline; debate SKOS mapping candidates; guide human review |
| `/schema-align` | Run schema alignment pipeline; debate field mapping candidates; guide human review |
| `/review-mappings` | Open an existing output directory for debate-driven review |
| `/validate-and-export` | Run pre-export checks and regenerate output artefacts |

Commands are defined in `.claude/commands/*.md` at the repository root — the standard Claude Code custom command location.

## Three-agent debate system

Every mapping review runs a **Structured Evidence Debate (SED)** with three agents:

| Agent | File | Role |
|-------|------|------|
| **Source Schema Advocate** | `agents/source-schema-advocate.md` | Speaks for the source data; argues whether proposed mappings correctly characterise what the source field means |
| **Target Schema Advocate** | `agents/target-schema-advocate.md` | Speaks for the target schema/ontology; argues whether proposed predicates or operations are semantically appropriate |
| **Mapping Mediator** | `agents/mapping-mediator.md` | Runs debate rounds; applies Elo-based scoring and penalties; ranks candidates; produces cross-mapping consistency report |

### Debate protocol summary

For each source entity/field:
1. **Round 0** (mediator): injects pipeline context — confidence, adversarial flags, information loss, evidence
2. **Round 1** (both advocates independently): each produces 1–3 FOR/AGAINST arguments with evidence type, claim, confidence, and counterpoint weakness
3. **Round 2** (cross-examination): each advocate sees the other's Round 1 and may produce 0–2 rebuttals
4. **Scoring** (mediator): computes pairwise Elo updates per argument, applies blocking-condition penalties, and re-ranks candidates by final Elo

### Elo ranking

Each candidate starts with an Elo rating derived from pipeline confidence: `initial_elo = 1000 + round(confidence × 800)`.

Each argument triggers pairwise Elo updates between the argued candidate and every other candidate for that source entity. The K-factor scales by evidence type weight and argument confidence: `K = 32 × weight[evidence_type] × argument.confidence`. Updates are zero-sum and applied in argument order so later arguments reflect current standings.

After debate, flat Elo penalties are deducted for blocking conditions:
- Pipeline adversarial severity `high` → −150 Elo
- `skos:exactMatch` present → −200 Elo (ontology)
- Unrebutted `information_loss` → −100 Elo (schema)
- Either advocate net negative for this candidate → −50 Elo each

Candidates are re-ranked by final Elo. Rank inversions (debate rank ≠ pipeline rank) are flagged and reported. Ambiguous top-1 = Elo gap < 50; strong isolation = gap > 200.

### Cross-mapping consistency

After all per-entity debates, the mediator produces a consistency report covering: target collisions, SKOS symmetry violations (ontology), rank inversions, ambiguous top-1 selections, strong isolations, coverage by entity type, and unit companion gaps (schema).

## How adversarial and meta-reviewer roles are handled

The previous four-persona architecture (ontology-engineer, data-integration, adversarial, meta) has been replaced:

| Old persona | Absorbed into |
|-------------|---------------|
| Ontology Engineer Reviewer | Target Schema Advocate (ontology-align role) |
| Data Integration Reviewer | Target Schema Advocate (schema-align role) |
| Adversarial Reviewer | Distributed: source advocate raises `ambiguity_unresolved`; target advocate raises `semantic_overreach`; mediator penalty multipliers encode overreach patterns |
| Meta Reviewer | Mediator cross-mapping consistency report |

## Reference documents

| Document | Contents |
|---------|---------|
| `references/mapping-status-model.md` | Complete status lifecycle for `validation_status` and `human_review_status` |
| `references/human-review-policy.md` | Mandatory review requirements; seven named principles |

## Architecture relationship

```
Python core (src/)
  ├── mapping_co_scientist/ontology_align/  ← ontology-align CLI
  ├── mapping_co_scientist/schema_align/    ← schema-align CLI
  └── mapping_co_scientist/shared/          ← shared models/agents

Claude Code plugin (.claude/ + claude-plugin/)
  ├── .claude/commands/*.md                 ← slash commands
  └── claude-plugin/
      ├── agents/                           ← three-agent debate definitions
      │   ├── source-schema-advocate.md
      │   ├── target-schema-advocate.md
      │   └── mapping-mediator.md
      ├── skills/                           ← skill documentation
      └── references/                       ← policy and status model docs
```

The plugin layer calls the Python CLIs from the host shell and runs the debate protocol on their output. It does not replicate, bypass, or replace the Python core.

## Limitations (v0.2.0)

- **No review persistence**: Human review decisions are recorded in the review session summary only. Writing decisions back to the candidates JSON requires the review ledger (planned for v0.3.0).
- **Lexical matching only**: Candidate generation uses rapidfuzz WRatio; LLM-backed semantic scoring is not yet integrated.
- **SHACL validation is a stub**: `shacl_adapter.py` exists but is not wired into the validation stage.
- **CSV sources only**: Both CLIs currently accept CSV sources; OpenAPI and JSON Schema source loading is not yet wired in.

## See also

- `CLAUDE.md` — project context, CLI reference, status model, critical constraints
- `CLAUDE_PLUGIN_TRANSITION_REPORT.md` — design decisions for the plugin scaffold and debate architecture
- `REPOSITORY_SPLIT_REPORT.md` — rationale for the ontology/schema split

# Mapping Co-Scientist — Claude Code Plugin

This directory contains the Claude Code plugin scaffold for the `mapping-co-scientist` package. It provides four slash commands, four reviewer personas, three skill definitions, and two reference documents for working with ontology alignment and schema field mapping pipelines.

## Quick start

1. Open this repository in Claude Code (CLI or IDE extension).
2. `CLAUDE.md` at the repository root provides project context automatically.
3. Run `/ontology-align` or `/schema-align` to start a pipeline and review session.

## Commands

| Command | Description |
|---------|-------------|
| `/ontology-align` | Run ontology alignment pipeline; review SKOS mapping candidates |
| `/schema-align` | Run schema alignment pipeline; review field mapping candidates |
| `/review-mappings` | Open an existing output directory for structured review |
| `/validate-and-export` | Run pre-export checks and regenerate output artefacts |

Commands are defined in `.claude/commands/*.md` at the repository root — this is the standard Claude Code custom command location.

## Reviewer personas

| Persona | Best for |
|---------|---------|
| `ontology-engineer-reviewer` | SKOS relation correctness, OWL safety |
| `data-integration-reviewer` | ETL operation correctness, datatype safety, information loss |
| `adversarial-reviewer` | Stress-testing pipeline assumptions |
| `meta-reviewer` | Cross-mapping consistency and collision detection |

Personas are referenced by commands; they are not separate slash commands.

## Reference documents

| Document | Contents |
|---------|---------|
| `references/mapping-status-model.md` | Complete status lifecycle for `validation_status` and `human_review_status` |
| `references/human-review-policy.md` | Mandatory review requirements; what the plugin may and may not do automatically |

## Architecture relationship

```
Python core (src/)
  ├── mapping_co_scientist/ontology_align/  ← ontology-align CLI
  ├── mapping_co_scientist/schema_align/    ← schema-align CLI
  └── mapping_co_scientist/shared/          ← shared models/agents

Claude Code plugin (.claude/ + claude-plugin/)
  ├── .claude/commands/*.md                 ← slash commands (actual Claude Code mechanism)
  └── claude-plugin/
      ├── agents/                           ← reviewer persona definitions
      ├── skills/                           ← skill documentation
      └── references/                       ← policy and status model docs
```

The plugin layer calls the Python CLIs via Bash; it does not replicate, bypass, or replace the Python core.

## Limitations (v0.2.0)

- **No review persistence**: Human review decisions are recorded in the review session summary only. Writing decisions back to the candidates JSON requires the review ledger (planned for v0.3.0).
- **Lexical matching only**: Candidate generation uses rapidfuzz WRatio; LLM-backed semantic scoring is not yet integrated in the new architecture.
- **SHACL validation is a stub**: The `shacl_adapter.py` exists but is not wired into the validation stage.
- **CSV sources only**: Both CLIs currently accept CSV sources; OpenAPI and JSON Schema source loading is not yet wired in.

## See also

- `CLAUDE.md` — project context, CLI reference, status model, critical constraints
- `CLAUDE_PLUGIN_TRANSITION_REPORT.md` — rationale and design decisions for the plugin scaffold
- `REPOSITORY_SPLIT_REPORT.md` — rationale and design decisions for the ontology/schema split

# Claude Code Plugin Transition Report

**Date**: 2026-05  
**Package version**: `mapping_co_scientist` v0.2.0  
**Plugin version**: 0.2.0  

---

## 1. Goals

The plugin scaffold connects the existing Python pipeline to Claude Code's slash command system, enabling:

1. **Guided pipeline execution**: Users can type `/ontology-align` or `/schema-align` and be walked through the full workflow without knowing the CLI arguments.
2. **Structured human review**: Every pipeline run produces candidates that require human decision; the plugin presents them in a structured, prioritised queue rather than leaving the user to read raw JSON.
3. **Reviewer persona specialisation**: Different people review ontology mappings (ontology engineers) vs schema mappings (data engineers) vs adversarial edge cases. The plugin encodes these review profiles explicitly.
4. **Policy enforcement**: Critical constraints (no auto-approval, no exactMatch from lexical similarity, no SSSOM from schema-align) are documented in `CLAUDE.md` and repeated in each command instruction file so they cannot be accidentally bypassed by Claude.

---

## 2. Claude Code conventions used

### Custom commands

Claude Code's actual mechanism for slash commands is `.claude/commands/*.md` files in the repository root. Each file's name (without `.md`) becomes the command name. The original spec proposed a `claude-plugin/commands/` directory; this was adapted to the actual Claude Code convention.

**Adaptation**: The four command files live in `.claude/commands/` (not `claude-plugin/commands/`). The `claude-plugin/` directory houses everything else (agents, skills, references) as documentation and reference material — not as a separate Claude Code feature.

### CLAUDE.md

The `CLAUDE.md` file at the repository root is automatically loaded by Claude Code as project context. It contains:
- Both CLI commands with full argument syntax
- Output artifact names per tool
- Hypothesis status fields and complete mapping status lifecycle
- Critical constraints (non-negotiable rules Claude must follow)
- Reviewer persona file paths

### Agent personas

Claude Code does not have a formal "agent file" mechanism distinct from custom commands. The four persona files in `claude-plugin/agents/` are reference documents that command files cite using relative paths. Claude reads them as part of command execution context when a command says "see `claude-plugin/agents/ontology-engineer-reviewer.md`."

---

## 3. File inventory

### New files created

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Project context loaded automatically by Claude Code |
| `.claude/commands/ontology-align.md` | `/ontology-align` slash command |
| `.claude/commands/schema-align.md` | `/schema-align` slash command |
| `.claude/commands/review-mappings.md` | `/review-mappings` slash command |
| `.claude/commands/validate-and-export.md` | `/validate-and-export` slash command |
| `claude-plugin/.claude-plugin/plugin.json` | Plugin metadata (for tooling; not a Claude Code runtime file) |
| `claude-plugin/agents/ontology-engineer-reviewer.md` | Ontology reviewer persona |
| `claude-plugin/agents/data-integration-reviewer.md` | Schema/ETL reviewer persona |
| `claude-plugin/agents/adversarial-reviewer.md` | Adversarial challenge persona |
| `claude-plugin/agents/meta-reviewer.md` | Cross-mapping consistency persona |
| `claude-plugin/skills/ontology-alignment/SKILL.md` | Ontology alignment skill documentation |
| `claude-plugin/skills/schema-mapping/SKILL.md` | Schema mapping skill documentation |
| `claude-plugin/skills/mapping-review/SKILL.md` | Mapping review skill documentation |
| `claude-plugin/references/mapping-status-model.md` | Complete status lifecycle reference |
| `claude-plugin/references/human-review-policy.md` | Mandatory human review policy |
| `claude-plugin/README.md` | Plugin scaffold README |
| `scripts/read_run_summary.py` | Helper: reads pipeline output, produces structured Markdown review summary |

### Modified files

| File | Change |
|------|--------|
| `README.md` | Added "Claude Code Plugin" section pointing to `CLAUDE.md` and plugin commands |

### Unchanged files

All Python source files (`src/`), tests (`tests/`), example data (`examples/`), and `pyproject.toml` were not modified. The plugin scaffold is purely additive.

---

## 4. Design decisions

### Why `.claude/commands/` not `claude-plugin/commands/`

Claude Code's custom command mechanism looks specifically for `*.md` files in `.claude/commands/`. Files placed elsewhere would not be registered as slash commands. The `claude-plugin/` directory was retained as specified in the original brief for structured documentation (agents, skills, references) — but the commands themselves had to go in `.claude/commands/` to actually work.

### Why not fabricate a plugin runtime

The original brief mentioned a `plugin.json` metadata file. Claude Code does not have a plugin runtime that reads `plugin.json` at time of writing; this file is kept as documentation metadata for tooling and future compatibility, but it has no runtime effect.

### Why commands call the Python CLI via Bash rather than importing

The commands instruct Claude to run `python -m mapping_co_scientist.*.cli` as a Bash command and read the output. Alternatives considered:

1. **Import and call Python functions directly**: Would require Claude to have the package installed and importable in the session environment. Fragile; depends on PYTHONPATH setup.
2. **Parse JSON output directly in command instructions**: Would duplicate the parsing logic that `scripts/read_run_summary.py` provides, and would break when the JSON schema changes.
3. **Use Bash to call CLI + read_run_summary.py**: Keeps Claude as an orchestrator, the Python code as the ground truth, and the summary script as the stable interface. This is the chosen approach.

### Why `scripts/read_run_summary.py` exists

The plugin commands need a stable, human-readable summary of pipeline output. Reading the raw JSON candidates files directly would expose Claude to large JSON blobs that might overflow context and are harder to reason about than structured Markdown. The summary script provides:
- Run type detection
- Per-entity/field grouping with top-1 + alternatives
- Status icons for quick visual scanning
- All relevant warning and adversarial flag content

### Why four reviewer personas

| Persona | Rationale |
|---------|-----------|
| Ontology Engineer | Domain-specific rules (SKOS semantics, OWL hierarchy safety) that a general reviewer would miss |
| Data Integration | ETL-specific rules (datatype safety, unit handling, lossy transforms) that an ontology reviewer would not consider |
| Adversarial | Complementary to the default reviewer; catches cases where a plausible mapping is wrong for non-obvious reasons |
| Meta | Catches cross-mapping issues (collisions, inconsistencies) that are invisible when reviewing one mapping at a time |

These are reference documents, not separate Claude Code features. Any command can "apply" a persona by reading the file and following its rules.

---

## 5. What the plugin intentionally does NOT do

1. **Auto-approve mappings**: No command approves a mapping on behalf of the user, even for high-confidence, flag-free candidates.

2. **Modify Python source files**: The plugin scaffold is a read-and-guide layer. It calls CLIs and reads output; it does not write to hypothesis JSON files (the review ledger for that is planned for v0.3.0).

3. **Replicate validation logic**: Commands do not re-implement the validation checks in Python; they call the CLI and read its output.

4. **Assign `skos:exactMatch`**: This constraint is in `CLAUDE.md` and repeated in every relevant command. The plugin follows the same rule as the Python generator.

5. **Produce SSSOM from schema-align**: The constraint is in `CLAUDE.md` and in the `/schema-align` command. Schema-align outputs YAML and JSON specs only.

---

## 6. Known limitations

1. **Review persistence**: Decisions made during a plugin review session are recorded in the session summary only. Writing them back to the candidates JSON is not yet possible because the review ledger has not been ported to the new architecture (v0.3.0 priority).

2. **Slash commands are instructions, not code**: Claude Code custom commands are Markdown instruction files, not executable code. Their behaviour depends on Claude correctly following the instructions. There is no unit-testable implementation to verify.

3. **Persona files are read on demand**: The persona files in `claude-plugin/agents/` are not automatically loaded; they are loaded when a command explicitly references them. If Claude is given a command without reading the persona file first, the persona-specific rules may not be applied.

4. **No integration tests for plugin commands**: The Python core has 325+ tests. The plugin commands have no automated tests. Manual testing against the example outputs is required after any change to command files.

---

## 7. Recommended next steps

1. **v0.3.0: Review ledger persistence**
   - Port `review_ledger/` to work with both `OntologyMappingHypothesis` and `FieldMappingHypothesis`
   - Update `/review-mappings` and `/validate-and-export` commands to call the ledger CLI
   - Remove the "decisions are not persisted" limitation note from all commands

2. **v0.3.0: LLM-backed semantic scoring**
   - When `LLMCandidateGeneratorAgent` is ported to the new architecture, update the commands to note that confidence scores now include semantic similarity (not just lexical)
   - Update the debate advocate instructions to note that high confidence no longer implies only string similarity

3. **v0.3.0: SHACL validation integration**
   - When `shacl_adapter.py` is wired into `OntologyValidationAgent`, update `/validate-and-export` to report SHACL validation results
   - Remove the "SHACL not wired in" limitation note

4. **Long-term: Plugin manifest standard**
   - If Claude Code introduces a formal plugin manifest format, migrate `claude-plugin/.claude-plugin/plugin.json` to the standard schema

---

## Addendum: Four-persona → Three-agent debate architecture (v0.2.0 plugin revision)

### Why four sequential personas were replaced

The original plugin scaffold used four sequential reviewer personas: Ontology Engineer Reviewer, Data Integration Reviewer, Adversarial Reviewer, and Meta Reviewer. Each ran as a separate pass over the candidate set. This design had three weaknesses:

1. **No productive tension**: Reviewers worked sequentially and could not challenge each other's reasoning. The adversarial reviewer challenged the pipeline's output, but not the other reviewers' conclusions.
2. **Role overlap and gaps**: The ontology engineer and data integration reviewers both did some adversarial work; the meta reviewer duplicated some of their cross-mapping checks. There was no clear ownership model.
3. **Wrong abstraction level**: The personas were defined around professional roles (who you are) rather than epistemic positions (what you know and therefore can argue). The natural epistemic divide in mapping is source vs. target, not "ontology engineer" vs. "data engineer."

### What the three-agent debate provides

The Structured Evidence Debate (SED) architecture is grounded in the observation that every mapping dispute has exactly two legitimate epistemic positions: "here is what the source field means" and "here is what the target term/field requires." These map directly to the source and target advocates. The mediator is not a domain expert — it is a scoring and synthesis function.

This provides:
- **Productive tension by design**: Advocates argue opposite sides simultaneously and then rebut each other. The mediator scores all arguments, not just the strongest ones.
- **Adversarial challenge embedded structurally**: The `counterpoint_weakness` field on every FOR argument, and the advocate's duty to challenge low-confidence candidates, replaces the separate adversarial pass.
- **Meta-review always included**: The mediator's cross-mapping consistency report runs automatically after all per-entity debates — it is not a separate invocation.

### How the Elo ranking works

Each candidate starts with an Elo rating derived from pipeline lexical confidence:

```
initial_elo = 1000 + round(pipeline_confidence × 800)   → range [1000, 1800]
```

Every debate argument triggers a series of pairwise Elo matches between the argued candidate and every other candidate for the same source entity. The K-factor scales by evidence type weight and argument confidence:

```
K = 32 × weight[evidence_type] × argument.confidence
```

FOR arguments give the argued candidate a "win" (positive Elo swing); AGAINST arguments give it a "loss". Updates follow the standard Elo formula and are zero-sum between candidates. Arguments are processed in order so each update reflects the current standings before the next argument is applied.

After debate, flat Elo penalties are deducted for blocking conditions (exactMatch → −200, high adversarial → −150, unrebutted info loss → −100, advocate net negative → −50 each). Penalties are additive.

The final ranking is by descending Elo. Tier thresholds: Tier 1 below 1250, Tier 2 between 1250 and 1500, Tier 3 at or above 1500. Ambiguous top-1 = Elo gap < 50; strong isolation = gap > 200; debate-unmapped = best candidate Elo < 1150.

Evidence type weights encode domain knowledge: semantic overreach and information loss risk carry weight 0.18 (highest), while precedent consistency carries 0.08 (lowest). These are fixed heuristics in v0.2.0, consistent with the severity taxonomy in the Python pipeline's adversarial agents. When the LLM-backed candidate generator is integrated (v0.3.0), the base Elo and weight table may be recalibrated using annotation data from historical review sessions.

### Absorption table

| Old persona | Absorbed into |
|-------------|---------------|
| Ontology Engineer Reviewer | Target Schema Advocate when run type = ontology-align |
| Data Integration Reviewer | Target Schema Advocate when run type = schema-align |
| Adversarial Reviewer | Source advocate (`ambiguity_unresolved`), target advocate (`semantic_overreach`), mediator penalty multipliers |
| Meta Reviewer | Mediator cross-mapping consistency report (runs automatically) |

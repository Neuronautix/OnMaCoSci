# Repository Split Report

**Date**: 2024-06  
**From**: `ontology-mapping-co-scientist` v0.1.0  
**To**: `mapping-co-scientist` v0.2.0  

---

## 1. Prior Architecture Summary

The original repository was a single Python package (`ontology_mapping_co_scientist`) that provided one unified pipeline for "mapping anything to anything." It had:

- **One data model**: `MappingHypothesis` with SKOS predicates (skos:exactMatch, etc.)
- **One pipeline**: `run_mapping_pipeline()` covering source profiling → candidate generation → adversarial review → validation → export
- **One export format**: SSSOM-compliant TSV
- **One set of agents**: All ontology-focused (source profiler, ontology profiler, candidate generator, adversarial reviewer, validation agent, human review agent)
- **LLM integration**: Claude-backed semantic scoring, ontology engineer reviewer, domain scientist reviewer

The system was well-designed for ontology alignment but conflated it with a second use case — operational schema-to-schema field mapping — that has completely different requirements.

---

## 2. Problem with the Initial Unified Concept

| Dimension | What the old tool assumed | What schema mapping needs |
|-----------|--------------------------|--------------------------|
| Output | Semantic assertion (skos:closeMatch) | Operational transformation rule (copy, rename, convert) |
| Validation | Ontology hierarchy, domain/range, SHACL | Datatype compatibility, unit conversion, cardinality |
| Export | SSSOM TSV | YAML mapping spec, JSONata, RML |
| Human reviewer | Ontology engineer | Data engineer |
| Failure mode | Over-claiming exactMatch | Silent information loss |
| Core question | Does X semantically correspond to Y? | How should X be transformed into Y? |

Using one tool for both created:
1. Misleading output: schema field mappings would have SKOS predicates with no semantic grounding
2. Wrong validation: OWL hierarchy checks are meaningless for CSV-to-JSON field mapping
3. Wrong export: SSSOM for operational field transforms misleads consumers
4. Wrong escalation: different human-in-the-loop questions for each domain

---

## 3. Final Split Architecture

```
mapping_co_scientist/           (new package, v0.2.0)
  shared/                       ← common agentic infrastructure
    models/
      evidence.py               ← Evidence, Provenance (shared)
      review.py                 ← ValidationStatus, HumanReviewStatus, AdversarialFlag
      confidence.py             ← ConfidenceScore with labelled levels
      human_decision.py         ← HumanReviewAction, SuggestedAction
      source_entity.py          ← SourceEntity (shared input type)
    agents/
      base_agent.py             ← Abstract BaseAgent
    llm/
      provider_interface.py     ← Abstract LLMProviderInterface
      mock_provider.py          ← Deterministic mock (no API key needed)
      prompt_templates.py       ← PromptTemplate registry
    scoring/
      ranking.py                ← Generic rank_by_confidence utility
    reports/
      markdown_report_base.py   ← Abstract MarkdownReportBase
    io/
      common_serialization.py   ← write_json, read_json

  ontology_align/               ← Tool 1: CLI command "ontology-align"
    models/
      ontology_entity.py        ← OntologyTerm
      ontology_mapping_hypothesis.py  ← OntologyMappingHypothesis, OntologyRelation, SemanticWarning
      term_gap_proposal.py      ← TermGapProposal
    parsers/
      ontology_loader.py        ← YAML/JSON ontology profile loader
      source_concept_loader.py  ← CSV → SourceEntity
      jsonld_loader.py          ← JSON-LD stub
    agents/
      ontology_source_profiler.py
      ontology_target_profiler.py
      semantic_candidate_generator.py  ← Lexical baseline; never auto-exactMatch
      ontology_adversarial_reviewer.py ← Flags exactMatch/OWL overreach
      term_gap_agent.py               ← Identifies ontology gaps
      ontology_validation_agent.py
    validation/
      semantic_checks.py        ← exactMatch scope, hierarchy checks
      shacl_adapter.py          ← pyshacl wrapper (optional dep)
    exporters/
      sssom_exporter.py         ← SSSOM-compliant TSV with metadata header
      ontology_review_report.py ← Markdown human review report
      jsonld_exporter.py        ← JSON-LD stub (future)
    pipeline.py                 ← 6-stage orchestrator
    cli.py                      ← argparse CLI: ontology-align

  schema_align/                 ← Tool 2: CLI command "schema-align"
    models/
      schema_entity.py          ← SchemaEntity (source or target field)
      field_mapping_hypothesis.py  ← FieldMappingHypothesis, CardinalityRelation
      transformation_rule.py    ← TransformationRule, MappingOperation
      lossiness_report.py       ← LossyMapping, LossinessReport
    parsers/
      csv_schema_loader.py      ← CSV → SchemaEntity (with unit inference)
      json_schema_loader.py     ← JSON Schema → SchemaEntity (recursive)
      openapi_loader.py         ← OpenAPI → SchemaEntity
      example_record_profiler.py
    agents/
      source_schema_profiler.py
      target_schema_profiler.py
      field_candidate_generator.py   ← Lexical field matching + unit constant inference
      schema_adversarial_reviewer.py ← Flags type mismatch, info loss, ambiguous counts
      mapping_rule_generator.py      ← Extracts TransformationRule from hypotheses
      schema_validation_agent.py
    validation/
      datatype_checks.py        ← Datatype compatibility
      cardinality_checks.py     ← Cardinality mismatch detection
      lossiness_checks.py       ← LossinessReport builder (unique source path counting)
      transformation_tests.py   ← Test rules against example records
    exporters/
      generic_mapping_exporter.py     ← YAML mapping specification
      transformation_spec_exporter.py ← JSON transformation rules
      schema_review_report.py         ← Markdown human review report
    pipeline.py                 ← 7-stage orchestrator
    cli.py                      ← argparse CLI: schema-align

ontology_mapping_co_scientist/  (original package, preserved for backwards compatibility)
  → All existing CLI commands (omcs-run, omcs-review) still work
```

---

## 4. Reused Components

| Component | Location | Reused by |
|-----------|----------|-----------|
| `Evidence`, `Provenance` | `shared/models/evidence.py` | Both tools |
| `ValidationStatus`, `HumanReviewStatus` | `shared/models/review.py` | Both tools |
| `AdversarialFlag`, `AdversarialReviewResult` | `shared/models/review.py` | Both tools |
| `ConfidenceScore` | `shared/models/confidence.py` | Both tools |
| `HumanReviewAction`, `SuggestedAction` | `shared/models/human_decision.py` | Both tools |
| `SourceEntity` | `shared/models/source_entity.py` | Both tools (different context) |
| `BaseAgent` | `shared/agents/base_agent.py` | All agents in both tools |
| `LLMProviderInterface` | `shared/llm/provider_interface.py` | Future LLM integration |
| `MockLLMProvider` | `shared/llm/mock_provider.py` | Tests for both tools |
| `rank_by_confidence` | `shared/scoring/ranking.py` | Both pipelines |
| `MarkdownReportBase` | `shared/reports/markdown_report_base.py` | Both report generators |
| `write_json` | `shared/io/common_serialization.py` | Both pipelines |

---

## 5. New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `OntologyRelation` | `ontology_align/models/` | SKOS + OWL + custom predicates (replaces generic `MappingPredicate`) |
| `OntologyMappingHypothesis` | `ontology_align/models/` | Ontology-specific hypothesis with semantic warnings, hierarchy checks |
| `SemanticWarning` | `ontology_align/models/` | Structured ontology semantic issue |
| `TermGapProposal` | `ontology_align/models/` | Proposed new ontology term |
| `SemanticCandidateGeneratorAgent` | `ontology_align/agents/` | Lexical baseline; enforces no-auto-exactMatch rule |
| `OntologyAdversarialReviewerAgent` | `ontology_align/agents/` | Flags exactMatch/equivalentClass overreach |
| `TermGapAgent` | `ontology_align/agents/` | Identifies unmapped source concepts |
| `SchemaEntity` | `schema_align/models/` | Schema field with unit, enumeration, path |
| `FieldMappingHypothesis` | `schema_align/models/` | Schema-specific hypothesis with transformation rules |
| `MappingOperation` | `schema_align/models/` | Transformation vocabulary (not SKOS predicates) |
| `TransformationRule` | `schema_align/models/` | Executable mapping specification |
| `LossinessReport` | `schema_align/models/` | Field coverage and information loss analysis |
| `FieldCandidateGeneratorAgent` | `schema_align/agents/` | Lexical field matching with unit constant inference |
| `SchemaAdversarialReviewerAgent` | `schema_align/agents/` | Flags type mismatch, info loss, ambiguous measurements |
| `MappingRuleGeneratorAgent` | `schema_align/agents/` | Consolidates rules from hypotheses |
| `generic_mapping_exporter.py` | `schema_align/exporters/` | YAML mapping spec (not SSSOM) |
| `transformation_spec_exporter.py` | `schema_align/exporters/` | JSON transformation rules |

---

## 6. Renamed or Removed Abstractions

| Old | New | Reason |
|-----|-----|--------|
| `MappingHypothesis` (generic) | `OntologyMappingHypothesis` + `FieldMappingHypothesis` | Two distinct concepts; generic name was misleading |
| `MappingPredicate` (SKOS only) | `OntologyRelation` (ontology) + `MappingOperation` (schema) | SKOS predicates are not appropriate for schema transformation |
| `ontology_mapping_co_scientist` package | `mapping_co_scientist` package | Old name implied only ontology use case |
| `REQUIRES_TRANSFORM` predicate | `MappingOperation.DATATYPE_CONVERSION` (schema) | Was a workaround in the unified model; now properly typed |
| `omcs-run` / `omcs-review` | `ontology-align` / `schema-align` | More descriptive; old commands preserved for compatibility |

---

## 7. Commands to Run Both Examples

### Ontology Alignment

```bash
# Using the script
python scripts/run_ontology_example.py

# Using the CLI directly
python -m mapping_co_scientist.ontology_align.cli \
  --source examples/ontology_align/inputs/animal_fields.csv \
  --ontology examples/ontology_align/inputs/hcm_profile.yaml \
  --output-dir examples/ontology_align/outputs \
  --verbose
```

### Schema Mapping

```bash
# Using the script
python scripts/run_schema_example.py

# Using the CLI directly  
python -m mapping_co_scientist.schema_align.cli \
  --source examples/schema_align/inputs/source_animal_records.csv \
  --target-schema examples/schema_align/inputs/metadatapp_import_schema.json \
  --output-dir examples/schema_align/outputs \
  --verbose
```

### Running Tests

```bash
# New architecture tests
python -m pytest tests/shared/ tests/ontology_align/ tests/schema_align/ -v

# Full test suite (includes original package tests)
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=src/mapping_co_scientist
```

---

## 8. Generated Output Files

### Ontology Alignment Outputs (`examples/ontology_align/outputs/`)

| File | Contents |
|------|----------|
| `ontology_mapping_candidates.json` | 27 OntologyMappingHypothesis objects with evidence, warnings, and provenance |
| `ontology_mapping_candidates.sssom.tsv` | SSSOM-compliant TSV with metadata header and SKOS predicates |
| `ontology_review_report.md` | Human-readable review grouped by source entity with adversarial flags |
| `term_gap_proposals.json` | Proposed new ontology terms for unmapped concepts |

**Key result**: `strain → hcm:GeneticBackground` uses `skos:narrowMatch` (not exactMatch) with a scope warning. No exactMatch is auto-assigned from lexical similarity alone.

### Schema Alignment Outputs (`examples/schema_align/outputs/`)

| File | Contents |
|------|----------|
| `field_mapping_candidates.json` | 27 FieldMappingHypothesis objects with transformation rules |
| `approved_mapping_spec.yaml` | YAML mapping spec with operations, units, and constant assignments |
| `transformation_rules.json` | 26 TransformationRule objects (JSON) |
| `transformation_validation_report.md` | Human review report with adversarial flags |
| `unmapped_fields_report.md` | Source fields with no suitable target |
| `information_loss_report.json` | Structured lossiness analysis |

**Key results**: 
- `Weight_g → measurements.bodyWeight.value` (NESTED_PATH)
- `measurements.bodyWeight.unit = "g"` (CONSTANT_ASSIGNMENT inferred from column suffix)
- `ActivityCount` flagged as ambiguous measurement requiring contextual definition
- No `.sssom.tsv` file created (schema-align is not an ontology tool)

---

## 9. Current Limitations

1. **Lexical-only candidate generation**: Both tools use rapidfuzz WRatio as the only similarity measure. Semantic similarity (embeddings, LLM scoring) is not yet integrated in the new package (the old package has it via `LLMCandidateGenerator`).

2. **JSON-LD exporter is a stub**: `ontology_align/exporters/jsonld_exporter.py` produces a simplified structure, not a fully compliant JSON-LD mapping.

3. **No SPARQL or RDF reasoning**: The new ontology_align package does not yet invoke SHACL/SPARQL validation; the old package's `shacl_validator.py` and `sparql_competency.py` are not yet ported.

4. **CSV sources only (new package)**: Both new CLIs currently only accept CSV sources. The old package's OpenAPI and JSON Schema source loaders exist in `schema_align/parsers/` but are not yet wired into the pipelines.

5. **No human review persistence**: The old `review_ledger` module is not yet ported to the new architecture.

6. **Term gap agent produces stubs only**: `TermGapAgent` creates placeholder proposals; LLM-driven definition drafting is not implemented.

7. **ActivityCount detection is heuristic**: The ambiguity detection for count/index fields uses keyword matching, not semantic reasoning.

8. **Coverage calculation counts unique source paths only**: Constant-assignment targets (no source path) are excluded from field coverage numerics.

---

## 10. Technical Debt

1. **Two separate `SourceEntity` loaders**: `ontology_align/parsers/source_concept_loader.py` and `schema_align/parsers/csv_schema_loader.py` both load CSV files but produce different types (`SourceEntity` vs `SchemaEntity`). A unified loader with a conversion layer would be cleaner.

2. **Import boundary not enforced by tooling**: The rule "schema_align must not import from ontology_align" is stated in the architecture decision document but not enforced by import linting rules. Add an `import-linter` configuration.

3. **Old package coexists**: `ontology_mapping_co_scientist` and `mapping_co_scientist.ontology_align` have overlapping functionality. The old package should be deprecated in v0.3.0.

4. **No shared orchestrator base**: Both `pipeline.py` files implement the 7-stage workflow independently. A shared `PipelineBase` class could reduce duplication, but it was intentionally deferred to avoid premature abstraction.

5. **Mock provider is simplistic**: `MockLLMProvider` uses keyword matching. A more realistic mock would use JSON fixtures for deterministic test scenarios.

---

## 11. Recommended Next Iteration (v0.3.0)

**Priority 1: Port LLM agents to the new architecture**
- Adapt `LLMCandidateGeneratorAgent` → `mapping_co_scientist.ontology_align.agents.llm_semantic_generator`
- Adapt `LLMAdversarialReviewerAgent` → shared interface usable by both tools
- Wire into both pipelines behind the `LLMProviderInterface`

**Priority 2: Complete source format support**
- Wire OpenAPI loader into both CLIs
- Wire JSON Schema source loading into both CLIs
- Port JSON-LD ontology loading from the old package

**Priority 3: Port the review ledger**
- Adapt `review_ledger/` to work with both `OntologyMappingHypothesis` and `FieldMappingHypothesis`
- Use a shared persistence protocol in `shared/`

**Priority 4: Add SHACL validation to ontology-align**
- Port `shacl_validator.py` as `ontology_align/validation/shacl_adapter.py` (stub already in place)
- Integrate with `OntologyValidationAgent`

**Priority 5: Enforce architectural boundaries**
- Add `import-linter` rules: `schema_align` may not import `ontology_align`; vice versa
- Add CI check for cross-boundary imports

**Priority 6: Improve transformation specification**
- Add JSONata expression generation for NESTED_PATH and DATATYPE_CONVERSION rules
- Add RML output option (behind explicit `--rdf-target` flag) for schema-align

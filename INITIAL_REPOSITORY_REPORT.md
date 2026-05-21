# Initial Repository Report

**Repository**: ontology-mapping-co-scientist  
**Version**: 0.1.0  
**Generated**: 2026-05-21  
**Branch**: claude/ontology-mapping-co-scientist-hrCH2

---

## 1. What Was Implemented

### Repository Structure
The full scaffold described in the specification was created:

```
ontology-mapping-co-scientist/
  README.md                              # Project overview and quick start
  pyproject.toml                         # Build config, dependencies, entry points
  LICENSE                                # MIT 2025
  .gitignore
  docs/
    architecture.md                      # System design and data flow
    mapping_hypothesis_model.md          # Full data model specification
    agent_roles.md                       # Agent role descriptions
    human_in_the_loop.md                 # Review philosophy and workflow guide
    roadmap.md                           # 6-phase development roadmap
  examples/
    source_csv/animal_metadata.csv       # 15-row mouse HCM experiment dataset
    source_openapi/animal_api_sample.json# OpenAPI 3.0 Animal Metadata API
    ontology_profiles/hcm_mouse_profile.yaml  # 12-term mouse phenotyping ontology
    outputs/                             # Generated at runtime (see below)
  src/ontology_mapping_co_scientist/
    models/                              # Core Pydantic data models
    agents/                              # All 8 agent implementations
    io/                                  # Loaders and exporters
    scoring/                             # Lexical similarity and evidence scoring
    pipeline/                            # Entry point and argparse CLI
    reports/                             # Markdown report generator
  tests/                                 # 114 pytest tests (all passing)
  scripts/run_example.py                 # Runnable end-to-end demo
  INITIAL_REPOSITORY_REPORT.md          # This file
```

### Core Data Models (src/models/)
- **`SourceEntity`**: represents one field from a source schema (CSV column, API property) with entity_id, label, datatype, examples, and provenance metadata
- **`OntologyTerm`**: represents one term from a target ontology with term_id, label, definition, synonyms, parent terms, and hierarchy context
- **`MappingHypothesis`**: the central data structure — a single candidate mapping with predicate, confidence, evidence list, counter-evidence list, warnings, validation status, human review status, and provenance
- **`Evidence` / `Provenance`**: supporting models for traceable reasoning
- **`AdversarialReviewResult`**, **`SuggestedAction`**: models for review outputs

### IO Layer (src/io/)
- **`csv_loader.py`**: loads CSV, infers datatypes, extracts example values per column
- **`openapi_loader.py`**: loads OpenAPI 3.x JSON, extracts properties from `components/schemas`
- **`ontology_profile_loader.py`**: loads YAML/JSON ontology profiles
- **`exporters.py`**: exports to JSON (with metadata envelope) and SSSOM-inspired TSV

### Scoring (src/scoring/)
- **`lexical_similarity.py`**: `rapidfuzz.fuzz.WRatio` with `difflib` fallback; label normalisation; `label_to_predicate` heuristic mapping scores to SKOS predicates
- **`evidence_scoring.py`**: builds typed `Evidence` objects; aggregates confidence from evidence/counter-evidence lists

### Agents (src/agents/)
All 8 agents are fully implemented:

| Agent | Status |
|-------|--------|
| `OrchestratorAgent` | Full — wires all agents, manages pipeline run |
| `SourceProfilerAgent` | Full — CSV and OpenAPI profiling with auto-detection |
| `OntologyProfilerAgent` | Full — loads profile, builds label/synonym index |
| `CandidateGeneratorAgent` | Full — generates up to N candidates per source entity |
| `AdversarialReviewerAgent` | Full — 9 flag types, applies flags back as counter-evidence |
| `RankingAgent` | Full — penalty-adjusted scoring, assigns rank per source entity |
| `HumanReviewAgent` | Full — suggested action logic, review packet generation |
| `ValidationAgent` | Full — consistency checks, validation summary |

### Pipeline (src/pipeline/)
- `run_mapping_pipeline.py`: `run_pipeline()` function + `main()` argparse CLI
- Entry point: `omcs-run` (installed via pyproject.toml)

### Reports (src/reports/)
- `markdown_report.py`: generates a structured review report with quick-index, per-entity sections (top mapping, alternatives, evidence, warnings, suggested action), and a statistics summary

### Tests (tests/)
114 tests across 4 modules, all passing:
- `test_source_profiler.py` (28 tests): CSV/OpenAPI loading, datatype inference, auto-detection
- `test_candidate_generator.py` (44 tests): hypothesis generation, adversarial review, ranking
- `test_exporters.py` (19 tests): JSON export structure, TSV column names, round-trip
- `test_pipeline.py` (23 tests): end-to-end integration with tmp_path fixtures

---

## 2. Architecture Map to Multi-Agent Concept

The specification defined 10 conceptual agent roles. Here is how they map to the implementation:

| Conceptual Role | Implementation |
|-----------------|---------------|
| Orchestrator Agent | `OrchestratorAgent` — full implementation |
| Source Profiler Agent | `SourceProfilerAgent` — full implementation |
| Ontology Profiler Agent | `OntologyProfilerAgent` — full implementation |
| Candidate Generator Agent | `CandidateGeneratorAgent` — full (lexical only, LLM extension point present) |
| Domain Scientist Reviewer | **Not yet a separate agent** — represented by `HumanReviewAgent` output packets and `AdversarialReviewerAgent` heuristics |
| Ontology Engineer Reviewer | **Not yet a separate agent** — `ValidationAgent` covers basic logical checks |
| Data/API Engineer Reviewer | **Not yet a separate agent** — adversarial flags cover datatype, unit, identifier heuristics |
| Adversarial Reviewer | `AdversarialReviewerAgent` — full implementation |
| Ranking Agent | `RankingAgent` — full implementation |
| Human Review Agent | `HumanReviewAgent` — full (output-only; no interactive UI yet) |
| Validation Agent | `ValidationAgent` — basic checks; SHACL/SPARQL planned in Phase 3 |

The three missing reviewer agents (Domain Scientist, Ontology Engineer, Data/API Engineer) are the primary target for Phase 2 (LLM integration), where each can be given a different system prompt and specialised reasoning task.

---

## 3. How to Run the Example

### Prerequisites
```bash
pip install -e ".[dev]"
# or without build isolation if needed:
pip install -e . --no-build-isolation
```

### Run the example pipeline
```bash
python scripts/run_example.py
```

This runs two pipeline passes:
1. OpenAPI source (`examples/source_openapi/animal_api_sample.json`)
2. CSV source (`examples/source_csv/animal_metadata.csv`)

Both use `examples/ontology_profiles/hcm_mouse_profile.yaml` as the target ontology.

### Run with custom inputs
```bash
omcs-run --source examples/source_csv/animal_metadata.csv \
         --ontology examples/ontology_profiles/hcm_mouse_profile.yaml \
         --output-dir examples/outputs \
         --verbose
```

### Run tests
```bash
PYTHONPATH=src pytest tests/ -v
```

---

## 4. Output Files Generated

Each pipeline run produces three files, timestamped with the run ID:

### `*_mappings.json`
Complete serialisation of all mapping hypotheses. Structure:
```json
{
  "metadata": {
    "generated_at": "2026-05-21T18:30:57Z",
    "total_mappings": 80,
    "pipeline_version": "0.1.0"
  },
  "mappings": [
    {
      "mapping_id": "...",
      "source_entity": { ... },
      "target_entity": { ... },
      "predicate": "skos:exactMatch",
      "confidence": 0.925,
      "evidence": [ ... ],
      "counter_evidence": [ ... ],
      "warnings": [ ... ],
      "validation_status": "passed",
      "human_review_status": "awaiting_review",
      "provenance": { ... }
    }
  ]
}
```

### `*_sssom.tsv`
SSSOM-inspired tab-separated file for interoperability with mapping tools. Columns: `mapping_id`, `subject_id`, `subject_label`, `predicate_id`, `object_id`, `object_label`, `confidence`, `mapping_justification`, `comment`. Header comment block explains the SSSOM inspiration and deviations.

### `*_review_report.md`
Human-readable Markdown review report. Includes:
- Quick index with top mapping per entity
- Per-entity sections with evidence tables, warnings, alternatives, suggested action
- Statistics summary (by predicate, confidence bucket, suggested action)

For the OpenAPI example run:
- 16 source entities extracted (Animal + Tissue schemas)
- 80 candidate hypotheses generated (top 5 per entity)
- 14 "approve" suggestions, 2 "request_more_evidence"
- All 80 hypotheses passed validation

---

## 5. Current Limitations

### Algorithmic limitations
- **Lexical similarity only**: the system measures string overlap between labels, not semantic understanding. "weight_g" matching "body weight" works because the labels share tokens; "BMI" matching "body mass index" would score poorly.
- **No synonym expansion**: only synonyms already present in the loaded ontology profile are used. No automatic synonym generation.
- **No definition-based matching**: ontology term definitions are stored but not used in scoring.
- **BROAD vs NARROW ambiguity**: the system cannot determine from lexical similarity alone whether a match is broader or narrower — it uses BROAD_MATCH as a placeholder for mid-range scores.

### Coverage limitations
- Only CSV and OpenAPI 3.x sources are supported (no JSON Schema, RDF, OWL, Markdown, JSON-LD)
- Only YAML/JSON flat ontology profiles are supported (no OWL ontology loading, no SPARQL endpoint querying)

### Output limitations
- SSSOM output is inspired by but not fully compliant with the SSSOM standard (missing required metadata headers, uses simplified predicate vocabulary)
- No JSON-LD export
- No RO-Crate packaging

### Review limitations
- Human review is read-only — there is no interface to record a reviewer's decision back into the system
- No multi-reviewer workflow
- No conflict resolution

---

## 6. Recommended Next Development Steps

In priority order:

1. **Add definition-based matching** (2–3 days): use TF-IDF or sentence-transformer embeddings on ontology term definitions to supplement lexical similarity. No LLM required. High impact.

2. **Implement full SSSOM compliance** (1–2 days): add required YAML header block, correct predicate IRIs (SKOS namespace), and `mapping_set_id`. Enables interoperability with Biomappings and other SSSOM tools.

3. **Add OWL ontology loader** (2–3 days): use `rdflib` to load OWL ontologies directly, extracting `rdfs:label`, `skos:altLabel`, `skos:definition`, `rdfs:subClassOf`. This removes the need for hand-crafted profiles.

4. **Implement JSON Schema source loader** (1 day): many APIs are described by JSON Schema; this extends coverage significantly.

5. **Add review recording** (2–3 days): extend `MappingHypothesis` serialisation to allow writing back review decisions via a simple CLI command or REST endpoint. Makes the human-in-the-loop workflow complete.

6. **Integrate an LLM for semantic review** (3–5 days): add `LLMAdversarialReviewerAgent` as a drop-in replacement for `AdversarialReviewerAgent`, using the Anthropic API. The evidence/counter-evidence model already supports LLM-generated Evidence objects.

---

## 7. Where LLM Agents Should Be Integrated

The architecture was designed with explicit LLM extension points:

### High-value, low-risk integration points

| Agent | LLM Role | How to Integrate |
|-------|----------|-----------------|
| `CandidateGeneratorAgent` | Semantic similarity assessment: given source field description + target term definition, score semantic overlap | Replace or augment `compute_similarity()` call; LLM output becomes an `Evidence` object with `evidence_type="llm_semantic_similarity"` |
| `AdversarialReviewerAgent` | Argue against proposed mappings from a domain science perspective | Add `_check_with_llm()` method; output becomes counter-evidence with `source="llm:claude-sonnet"` |
| `HumanReviewAgent` | Generate richer, context-aware suggested action text | Augment `suggest_action()` with LLM-generated natural-language justification |

### Separate LLM agent implementations (Phase 2)

| New Agent | LLM Task |
|-----------|----------|
| `LLMDomainScientistReviewerAgent` | "Does this mapping make scientific sense in the context of [domain]?" |
| `LLMOntologyEngineerReviewerAgent` | "Is this predicate type appropriate given the formal axioms of the ontology?" |
| `LLMDataEngineerReviewerAgent` | "What transformation would be needed to make this mapping operationally valid?" |

### Implementation pattern
All LLM-backed agents should:
1. Accept an optional `llm_client` parameter in `__init__`; if `None`, fall back to current lexical behaviour
2. Record LLM model name and prompt hash in `Provenance.extra`
3. Parse LLM output into structured `Evidence` objects — never return raw LLM text as a mapping decision
4. Log token usage for cost tracking

---

## 8. What Needs Human Expert Review

The following artefacts in this repository were generated algorithmically and require domain expert validation before use:

### Example data
- `examples/ontology_profiles/hcm_mouse_profile.yaml`: the 12 ontology terms and their definitions are plausible but **fictional** — they were generated to illustrate the data format. Before using this in any real mapping context, replace with terms from a real ontology (e.g., MP, MA, UBERON, OBI, NCIThesaurus).
- `examples/source_openapi/animal_api_sample.json`: the API schema is realistic but fictional.
- `examples/source_csv/animal_metadata.csv`: the data values (strains, genotypes) are plausible but not from a real experiment.

### Generated mappings
- **All mappings in `examples/outputs/`** are machine-generated hypotheses. They should not be used as authoritative mappings without expert review.
- Notable cases that need careful review:
  - `storage_condition` → `mbo:AgeAtMeasurement`: this mapping has a low confidence and is clearly wrong — it is a useful example of why human review is essential
  - `collection_date` → `mbo:TissueCollection`: the predicate may need to be `skos:broadMatch` rather than the suggested match

### Architecture decisions for expert validation
- The `label_to_predicate` score thresholds (0.90/0.75/0.55/0.40) are heuristic and were not validated against a gold standard mapping set. Domain experts using this system in a specific field should calibrate these thresholds against known correct mappings.
- The adversarial reviewer's flag severity ratings are heuristic and may need adjustment for specific use cases.

---

*This report was generated as part of the initial repository bootstrap. Update it as the system evolves.*

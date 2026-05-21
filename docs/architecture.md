# Architecture

This document describes the design of the ontology-mapping-co-scientist
system: its components, their interactions, the data flow through the
pipeline, and the extension points available for adding new agents, source
formats, or reasoning capabilities.

---

## Design philosophy

The system is built on four principles:

**1. Hypotheses, not facts.**
Every proposed mapping is represented as a `MappingHypothesis` — a falsifiable
claim supported by evidence that must be reviewed before it becomes an
authoritative mapping.  The data model enforces this at every layer.

**2. Separation of agent roles.**
Each pipeline stage is implemented as a distinct agent class with a clear input
type, output type, and single responsibility.  This separation makes individual
stages testable, replaceable (e.g. swapping lexical scoring for LLM-based
scoring), and independently understandable.

**3. Explicit provenance.**
Every hypothesis carries a `Provenance` object recording who created it, when,
by what method, and in which pipeline run.  Every mutation to a hypothesis
(validation status change, review decision, added warning) is also recorded.
Nothing is silently discarded.

**4. Human authority is final.**
The pipeline generates recommendations but makes no autonomous decisions.  The
`validation_status` field reflects automated checks; `human_review_status`
reflects human authority.  A mapping cannot be considered authoritative until
a human reviewer sets `human_review_status` to `approved`.

---

## System overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ontology-mapping-co-scientist                    │
│                                                                     │
│  INPUT FILES                   PIPELINE AGENTS                      │
│  ──────────                    ──────────────────────────────────   │
│  source.csv    ──►  SourceProfilerAgent ──► [SourceEntity list]     │
│  source.json   ──►                                                  │
│                                                                     │
│  profile.yaml  ──►  OntologyProfilerAgent ──► [OntologyTerm list]   │
│                                   │                                 │
│                                   ▼                                 │
│                    CandidateGeneratorAgent                          │
│                    (lexical similarity scoring)                     │
│                           │                                         │
│                           ▼                                         │
│                    [MappingHypothesis list]                         │
│                           │                                         │
│                           ▼                                         │
│                    AdversarialReviewerAgent ──► [AdversarialReviewResult]
│                           │                                         │
│                           ▼                                         │
│                    RankingAgent                                     │
│                    (rank hypotheses per entity)                     │
│                           │                                         │
│                           ▼                                         │
│                    ValidationAgent                                  │
│                    (set validation_status)                          │
│                           │                                         │
│                           ▼                                         │
│                    HumanReviewAgent                                 │
│                    (assemble review packets, SuggestedAction)       │
│                           │                                         │
│                           ▼                                         │
│  OUTPUT FILES     Export stage                                      │
│  ──────────────   ─────────────────────────────────────────────     │
│  mappings.json ◄─ export_to_json()                                  │
│  sssom.tsv     ◄─ export_to_sssom_tsv()                             │
│  report.md     ◄─ generate_markdown_report()                        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component descriptions

### `models/` — Data layer

Three modules define the core data structures.  All models are Pydantic
`BaseModel` subclasses, which provides automatic validation, serialisation,
and JSON schema generation.

- **`entities.py`** — `SourceEntity` and `OntologyTerm`.  These are plain
  value objects that carry raw facts.  They contain no mapping logic.

- **`mapping_hypothesis.py`** — `MappingHypothesis`, `Evidence`, `Provenance`,
  `MappingPredicate`, `ValidationStatus`, `HumanReviewStatus`.  This is the
  central data structure of the entire system.

- **`review.py`** — `AdversarialFlag`, `AdversarialReviewResult`,
  `HumanReviewAction`, `SuggestedAction`.  Models for the review and
  adversarial critique phases.

### `io/` — I/O layer

Loaders and exporters that handle file format details so that agents never
need to deal with raw file I/O.

- **`csv_loader.py`** — reads a CSV file, infers datatypes, produces
  `SourceEntity` objects (one per column).
- **`openapi_loader.py`** — parses OpenAPI 3.x / Swagger 2.x JSON, produces
  `SourceEntity` objects (one per schema property).
- **`ontology_profile_loader.py`** — reads a YAML/JSON ontology profile,
  produces `OntologyTerm` objects.
- **`exporters.py`** — serialises `MappingHypothesis` lists to JSON and SSSOM
  TSV.

### `scoring/` — Scoring utilities

Pure functions for computing similarity scores.  Agents call these functions;
they are never called directly from outside the package.

- **`lexical_similarity.py`** — `normalize_label()`, `compute_similarity()`,
  `find_best_matches()`, `label_to_predicate()`.
- **`evidence_scoring.py`** — `build_lexical_evidence()`,
  `build_synonym_evidence()`, `compute_aggregate_confidence()`.  (Required by
  `CandidateGeneratorAgent`; not present in the initial scaffold if not yet
  created.)

### `agents/` — Agent layer

Each agent class has a focused responsibility.  In the MVP, agents are
synchronous Python classes.  In future phases, some agents may become LLM
tool-call chains.

- **`SourceProfilerAgent`** — wraps the `io/` loaders with logging,
  auto-detection of file format by extension, and a `summarize()` method.
- **`OntologyProfilerAgent`** — wraps the ontology profile loader with an
  in-memory label/synonym index and a `get_candidates_for_label()` method.
- **`CandidateGeneratorAgent`** — the core mapping engine.  Uses scoring
  utilities to generate ranked candidate hypotheses.

### `pipeline/` — Orchestration layer

The pipeline module contains the `run_pipeline()` function, which chains all
agents in order, manages logging and output paths, and returns a result dict.
The adversarial reviewer, ranker, validator, and human review agent are
currently implemented inline in this module; they will be refactored into
separate agent classes in Phase 2.

### `reports/` — Report layer

The `markdown_report.py` module generates the human review report from the
assembled review packets.  It has no dependencies on the agents or scoring
modules — it only depends on the data models.

---

## Data flow

```
Source file (CSV / OpenAPI JSON)
    │
    ▼
SourceProfilerAgent.profile_auto()
    │  detects format, delegates to csv_loader / openapi_loader
    ▼
list[SourceEntity]
    │  entity_id, label, description, datatype, examples, source_type
    │
    │  ── parallel ──────────────────────────────────────────────────
    ▼
OntologyProfilerAgent.load_profile()
    │  parses YAML, builds label/synonym indexes
    ▼
list[OntologyTerm]
    │  term_id, label, definition, synonyms, parent_terms
    │  ────────────────────────────────────────────────────────────
    │
    ▼  (both lists consumed here)
CandidateGeneratorAgent.generate_candidates()
    │
    │  For each SourceEntity:
    │    1. find_best_matches(entity.label, term_labels, top_k=5)
    │    2. check synonym matches
    │    3. merge, deduplicate, sort by max(lex_score, syn_score)
    │    4. build Evidence objects (lexical + synonym)
    │    5. compute_aggregate_confidence()
    │    6. label_to_predicate(best_score)
    │    7. construct MappingHypothesis with Provenance
    │    8. if no candidates pass min_confidence: emit NO_MAPPING
    │
    ▼
list[MappingHypothesis]  (validation_status=PENDING, rank=None)
    │
    ▼
AdversarialReviewerAgent  (per hypothesis)
    │  checks: low_confidence, missing_definition, synonym_only_match,
    │          no_mapping_found, ambiguous_short_label
    ▼
dict[mapping_id → AdversarialReviewResult]
    │
    ▼
RankingAgent  (per source entity group)
    │  sort by (is_no_mapping, -confidence, mapping_id)
    │  assign rank 1..n
    ▼
list[MappingHypothesis]  (rank populated)
    │
    ▼
ValidationAgent  (per hypothesis)
    │  checks confidence bounds, evidence presence, rank-1 quality
    │  appends warnings to hypothesis.warnings
    │  sets hypothesis.validation_status
    ▼
list[MappingHypothesis]  (validation_status set)
    │
    ▼
HumanReviewAgent._build_review_packets()
    │  groups by entity, picks top hypothesis per entity
    │  calls _suggest_action() → SuggestedAction
    ▼
list[dict]  review_packets  (one per source entity)
    │
    ├──► export_to_json()           →  mappings.json
    ├──► export_to_sssom_tsv()      →  sssom.tsv
    └──► generate_markdown_report() →  review_report.md
```

---

## Agent interaction diagram

```
run_pipeline()
    │
    ├─[1]─► SourceProfilerAgent ──── reads file ──────────────────►  io/csv_loader
    │                                                                io/openapi_loader
    │
    ├─[2]─► OntologyProfilerAgent ── reads file ──────────────────►  io/ontology_profile_loader
    │           │                                                     scoring/lexical_similarity
    │           └── builds label_index, synonym_index
    │
    ├─[3]─► CandidateGeneratorAgent
    │           │  receives: source_entities, ontology_terms
    │           ├── scoring/lexical_similarity.find_best_matches()
    │           ├── scoring/evidence_scoring.build_lexical_evidence()
    │           ├── scoring/evidence_scoring.build_synonym_evidence()
    │           ├── scoring/evidence_scoring.compute_aggregate_confidence()
    │           └── scoring/lexical_similarity.label_to_predicate()
    │           └── produces: list[MappingHypothesis]
    │
    ├─[4]─► _adversarial_review()   (per hypothesis)
    │           └── produces: AdversarialReviewResult
    │
    ├─[5]─► _rank_hypotheses()
    │           └── mutates: hypothesis.rank
    │
    ├─[6]─► _validate_hypothesis()  (per hypothesis)
    │           └── mutates: hypothesis.validation_status, hypothesis.warnings
    │
    ├─[7]─► _build_review_packets()
    │           ├── _suggest_action()  (per top hypothesis)
    │           └── produces: list[dict] review_packets
    │
    ├─[8a]─► io/exporters.export_to_json()
    ├─[8b]─► io/exporters.export_to_sssom_tsv()
    └─[8c]─► reports/markdown_report.generate_markdown_report()
```

---

## Extension points

### Adding a new source format

To add support for a new source file format (e.g. JSON Schema, Parquet schema,
database introspection):

1.  Create a new loader module in `src/ontology_mapping_co_scientist/io/`,
    e.g. `jsonschema_loader.py`.  The loader must return a `list[SourceEntity]`.

2.  Add a new method to `SourceProfilerAgent`, e.g. `profile_json_schema()`.

3.  Extend `SourceProfilerAgent.profile_auto()` to detect the new format by
    file extension (or MIME type, or magic bytes).

4.  Add the new file extension to the CLI `--source` argument help text.

5.  Add tests in `tests/io/test_jsonschema_loader.py`.

No other changes are required; the rest of the pipeline is format-agnostic.

### Adding a new scoring strategy

To add a new evidence type (e.g. embedding cosine similarity, parent-term
overlap):

1.  Add a new function to `scoring/` (or a new module).  It should return an
    `Evidence` object.

2.  Call the new function inside `CandidateGeneratorAgent._generate_for_entity()`
    and append the resulting `Evidence` to `evidence_list`.

3.  Update `compute_aggregate_confidence()` in `evidence_scoring.py` if the
    new evidence type should affect the aggregate score.

4.  Add tests.

### Adding a new agent

To add a new agent (e.g. a `DefinitionEmbeddingAgent` that uses sentence
transformers):

1.  Create a new module in `agents/`, e.g. `definition_embedding_agent.py`.

2.  Define a class with a clear public method signature.  The method should
    accept `list[MappingHypothesis]` and return `list[MappingHypothesis]`
    with modified evidence or confidence fields.

3.  Register the agent in `run_pipeline()` after the `CandidateGeneratorAgent`
    step and before the adversarial review step.

4.  Update the agent interaction diagram in this document.

### Swapping in an LLM-backed agent

The design intentionally separates the *role* (what the agent decides) from
the *implementation* (how it decides).  To replace a rule-based agent with an
LLM call:

1.  Create a new class that implements the same method signature as the
    existing agent.

2.  Add LLM prompts and parsing logic to the new class.  The Evidence model
    has a `source` field specifically designed to record the agent name and
    can carry the LLM model version in `Provenance.extra`.

3.  Replace the existing agent instantiation in `run_pipeline()`.

4.  Keep the rule-based agent as a fallback or test double.

---

## Key design decisions and rationale

**Why Pydantic for data models?**
Pydantic provides runtime validation, clear field documentation, automatic
JSON serialisation via `model_dump(mode="json")`, and excellent IDE support.
The frozen/extra="forbid" configuration catches accidental field mutations and
typos immediately.

**Why a flat `list[MappingHypothesis]` rather than a graph?**
A flat list is simpler to serialise, iterate, and test.  The relationship
structure (multiple candidates per entity, ranking) is encoded via `rank` and
`source_entity.entity_id` fields, which are sufficient for all current use
cases.  A graph representation would be premature abstraction at this stage.

**Why inline the adversarial reviewer and ranking logic in `run_mapping_pipeline.py`?**
To keep the MVP surface area small and make the pipeline readable as a single
module.  When these stages become complex enough to warrant their own test
suites and configuration objects, they will be extracted into `agents/`
modules.  The refactor will be mechanical: move the function, update the
import in `run_pipeline()`.

**Why SSSOM-inspired rather than full SSSOM?**
Full SSSOM conformance requires a rich metadata header with IRI-based
identifiers for the mapping set, the creator, and the tool.  These require
infrastructure decisions (IRI schemes, identity management) that are out of
scope for an MVP.  The SSSOM-inspired export provides the core mapping data in
a format that SSSOM tooling can partially consume while being honest about its
non-conformance.

**Why Markdown for the review report rather than HTML or PDF?**
Markdown renders directly in GitHub, VS Code, Jupyter, and most scientific
collaboration platforms.  It is diffable, grep-able, and version-controllable.
Conversion to HTML or PDF is trivial with Pandoc if needed.

---

## How to add a new export format

To add a new output serialisation format (e.g. JSON-LD, OWL/XML, RDF Turtle):

1.  Add an export function to `io/exporters.py`, e.g. `export_to_jsonld()`.
    The function signature should be
    `(hypotheses: list[MappingHypothesis], output_path: Path) -> None`.

2.  Call the new export function in `run_pipeline()` after the existing exports
    and add the new output path to the result dict.

3.  Add the new output path to the CLI summary printed by `main()`.

4.  Update this document.

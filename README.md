# ontology-mapping-co-scientist

An AI co-scientist system for semi-automated ontology mapping of source data
entities (from CSV schemas, OpenAPI specifications, JSON Schema definitions,
and database columns) to terms in formal ontologies, with adversarial review,
confidence scoring, and a structured human-in-the-loop review workflow.

**Status**: Alpha / MVP — lexical-similarity pipeline is functional.
LLM-based semantic understanding and full SSSOM export are planned for
subsequent phases (see [Roadmap](docs/roadmap.md)).

---

## What is this project?

Research and clinical data systems capture biological and clinical observations
using field names, column headers, and API parameter names that are invented by
the data producer.  Two labs may call the same measurement "mouse strain",
"genetic background", "strain name", and "animal genotype" — all referring to
the same concept — and downstream data integration becomes impossible without
explicit, auditable, semantically precise mappings to a shared ontology.

Ontology mapping is tedious, expertise-intensive, and error-prone.  Done
manually it does not scale; done entirely automatically it produces silent
errors that corrupt downstream analyses.

**ontology-mapping-co-scientist** takes a middle path: it acts as an AI
*co-scientist* that generates **mapping hypotheses** supported by evidence and
adversarial critique, and then presents those hypotheses to a human expert for
review and approval.  The system handles the combinatorial grunt-work of
comparing thousands of label pairs; the human makes the final semantic
judgement.

The "co-scientist" framing is deliberate.  Like a scientific hypothesis, each
proposed mapping is treated as a falsifiable claim about the world that must be
tested and reviewed before it is accepted.

---

## Why are mappings treated as hypotheses?

This is the central design principle of the project.  A mapping is not a fact
until a qualified human has reviewed and approved it.  There are three reasons
for this:

**1. Lexical similarity is not semantic equivalence.**
Two labels that look the same or similar can refer to completely different
concepts.  "Sex" in a clinical data model and "sex" in a population genetics
model may have incompatible definitions.  A string-similarity algorithm cannot
detect this.

**2. Ontology terms have precise, formal definitions.**
Assigning the wrong SKOS predicate (for example, using `skos:exactMatch` when
the correct predicate is `skos:broadMatch`) introduces logical errors that
propagate silently through any system that consumes the mapping.

**3. Provenance and audit trails matter.**
In regulated research environments (clinical trials, pharmaceutical R&D,
published datasets) every mapping decision must be attributable to a named
human reviewer, with a date, a rationale, and a record of what evidence was
considered.  A fully automated system cannot provide this.

The system therefore treats every output as a *candidate* with an associated
confidence score, a list of supporting evidence, a list of adversarial flags,
and a structured recommendation for human action.  None of this output becomes
an authoritative mapping until a human reviewer explicitly approves it.

---

## Agent architecture

The pipeline is structured as a sequence of specialised agents, each with a
well-defined role.  The MVP implements all stages as Python classes; future
phases will replace heuristic implementations with LLM-backed reasoning.

| Agent | Role | MVP implementation |
|-------|------|--------------------|
| **SourceProfilerAgent** | Extracts and profiles source entities from input files (CSV, OpenAPI JSON).  Infers datatypes, collects example values, and normalises entity identifiers. | Rule-based extraction using `csv.DictReader` and JSON parsing |
| **OntologyProfilerAgent** | Loads an ontology profile (YAML/JSON), builds normalised label and synonym indexes for efficient candidate lookup. | In-memory dict-based index with label normalisation |
| **CandidateGeneratorAgent** | For each source entity, generates up to `top_k` mapping hypothesis candidates by comparing entity labels against ontology term labels and synonyms. | `rapidfuzz` token-sort and partial-ratio scoring |
| **AdversarialReviewerAgent** | Inspects each hypothesis for quality problems: low confidence, missing term definition, synonym-only matches, very short labels, and no-mapping outcomes. | Rule-based flag generation with severity levels |
| **RankingAgent** | Assigns an integer rank to each hypothesis within its source entity group, ordered by confidence score descending. | Sort by `(is_no_mapping, -confidence, mapping_id)` |
| **ValidationAgent** | Runs automated consistency checks and sets `validation_status` on each hypothesis. | Pydantic constraint checks plus evidence-presence checks |
| **HumanReviewAgent** | Assembles review packets (hypothesis + adversarial result + suggested action) and generates structured `SuggestedAction` recommendations. | Decision-tree rules based on confidence and adversarial flags |
| **ExportAgent** | Serialises approved hypotheses to JSON and SSSOM-inspired TSV; generates a Markdown review report. | `json.dump` + `csv.DictWriter` + Markdown string builder |

Three reviewer agent roles are **planned but not yet implemented** as separate
agents:
- **DomainScientistReviewer** — deep biological/clinical domain expertise
- **OntologyEngineerReviewer** — formal ontology structure and hierarchy checks
- **DataAPIEngineerReviewer** — data type, format, and transformation validation

---

## Quick start

### Prerequisites

- Python 3.11 or 3.12
- Git

### Installation

```bash
git clone https://github.com/your-org/ontology-mapping-co-scientist.git
cd ontology-mapping-co-scientist
pip install -e ".[dev]"
```

### Run the example

The example script runs two complete pipeline passes (one OpenAPI source, one
CSV source) against a sample HCM mouse ontology profile:

```bash
python scripts/run_example.py
```

Output files will appear in `examples/outputs/`.

### Run from the command line

After installation, the `omcs-run` console script is available:

```bash
omcs-run \
  --source examples/source_openapi/animal_api_sample.json \
  --ontology examples/ontology_profiles/hcm_mouse_profile.yaml \
  --output-dir examples/outputs \
  --verbose
```

### Run with LLM-assisted hypothesis and review generation

Install the LLM extra and set an Anthropic API key:

```bash
pip install -e ".[dev,llm]"
export ANTHROPIC_API_KEY="..."
```

You can also put the key in a local `.env` file at the repository root.  The
CLI loads this file automatically and `.env` is ignored by git:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
OMCS_LLM_MODEL=claude-haiku-4-5-20251001
OMCS_DOMAIN_CONTEXT=preclinical mouse metadata
OMCS_LLM_REVIEW_TOP_K=1
OMCS_LLM_CANDIDATE_TOP_K=2
OMCS_LLM_MAX_CANDIDATE_ENTITIES=10
OMCS_LLM_MAX_REVIEW_HYPOTHESES=10
OMCS_LLM_CALL_DELAY_SECONDS=1.0
```

Then enable the LLM-orchestrated path:

```bash
omcs-run \
  --source examples/source_openapi/animal_api_sample.json \
  --ontology examples/ontology_profiles/hcm_mouse_profile.yaml \
  --output-dir examples/outputs \
  --llm \
  --require-llm \
  --llm-review-top-k 1 \
  --llm-candidate-top-k 2 \
  --llm-max-candidate-entities 10 \
  --llm-max-review-hypotheses 10 \
  --domain-context "preclinical mouse metadata" \
  --verbose
```

With `--llm`, the pipeline uses LLM semantic scoring during candidate
generation and runs LLM adversarial, ontology-engineer, and domain-scientist
reviewers before HITL review.  Heuristic review still covers every generated
hypothesis; by default, each LLM reviewer reviews only the top-ranked
hypothesis per source entity to avoid provider overload.  Increase
`--llm-review-top-k` only when needed.  Without `--require-llm`, missing LLM
configuration falls back to deterministic non-LLM behavior and records the
fallback modes in the generated `*_review_queue.json`.

Cost control defaults are intentionally conservative:

- at most 10 source entities receive LLM candidate scoring;
- only the top 2 lexical candidates per scored entity are sent to the LLM;
- each LLM reviewer sees at most 10 hypotheses;
- heuristic review still evaluates every hypothesis.

Or directly via Python:

```bash
python -m ontology_mapping_co_scientist.pipeline.run_mapping_pipeline \
  --source examples/source_csv/animal_data_sample.csv \
  --ontology examples/ontology_profiles/hcm_mouse_profile.yaml \
  --output-dir examples/outputs \
  --run-id my-experiment-001 \
  --verbose
```

### Use as a library

```python
from ontology_mapping_co_scientist.pipeline.run_mapping_pipeline import run_pipeline

result = run_pipeline(
    source_filepath="data/animals.csv",
    ontology_filepath="profiles/hcm_mouse.yaml",
    output_dir="outputs/",
    pipeline_run_id="my-run-001",
    verbose=True,
)

print(f"Generated {result['total_hypotheses']} hypotheses")
print(f"Review report: {result['output_report']}")
```

---

## What the MVP does — step by step

1.  **Load source entities** — The `SourceProfilerAgent` reads your CSV or
    OpenAPI JSON file and extracts one `SourceEntity` per column/property.
    It infers the datatype (`string`, `number`, `boolean`) and collects up to
    three example values.

2.  **Load ontology terms** — The `OntologyProfilerAgent` reads a YAML
    ontology profile and builds an in-memory index of preferred labels and
    synonyms.

3.  **Generate candidates** — The `CandidateGeneratorAgent` compares each
    source entity label against every ontology term label and synonym using
    `rapidfuzz` fuzzy string matching.  Up to 5 candidates are proposed per
    entity.  A `custom:noMapping` hypothesis is emitted for entities that have
    no candidates above the minimum threshold.

4.  **Adversarial review** — Each hypothesis is inspected by the
    `AdversarialReviewerAgent` for quality problems: low confidence, missing
    ontology definitions, synonym-only matches, and ambiguous short labels.
    Problems are recorded as `AdversarialFlag` objects with severity levels
    (`low`, `medium`, `high`).

5.  **Ranking** — Hypotheses are ranked within each source entity group by
    confidence score descending.  `NO_MAPPING` hypotheses are always ranked
    last.

6.  **Validation** — The `ValidationAgent` runs automated consistency checks
    and sets `validation_status` (`passed`, `failed`, `warning`) on each
    hypothesis.

7.  **Assemble review packets** — The `HumanReviewAgent` assembles one review
    packet per source entity, containing the top hypothesis, the adversarial
    review result, and a structured `SuggestedAction` recommendation.

8.  **Export** — Three output files are written to the output directory:
    - A JSON file with the full hypothesis data
    - An SSSOM-inspired TSV file for tooling integration
    - A Markdown review report for human reviewers

---

## Output files

For each pipeline run, three files are written to the output directory.  The
file names include the source file stem and a UTC timestamp for traceability.

### `<stem>_<timestamp>_mappings.json`

A structured JSON document containing:
- `metadata` block: generation timestamp, total mapping count, pipeline version
- `mappings` array: one entry per `MappingHypothesis`, fully serialised including
  all evidence items, adversarial flags, validation status, and provenance

This file is the authoritative record of the pipeline run and can be used to
reconstruct the full state of every mapping decision.

### `<stem>_<timestamp>_sssom.tsv`

A tab-separated file inspired by the [Simple Standard for Sharing Ontological
Mappings (SSSOM)](https://mapping-commons.github.io/sssom/).  Contains only
hypotheses with a non-`NO_MAPPING` predicate and a resolved target entity.
Columns: `mapping_id`, `subject_id`, `subject_label`, `predicate_id`,
`object_id`, `object_label`, `confidence`, `mapping_justification`, `comment`.

Note: this is not a fully SSSOM-conformant file; full SSSOM compliance is
planned for Phase 4 of the roadmap.

### `<stem>_<timestamp>_review_report.md`

A Markdown document designed for direct reading by a domain scientist.  For
each source entity it shows:
- The top candidate mapping with evidence and adversarial flags
- Up to three alternative candidate mappings
- A structured suggested human action with a written rationale
- Provenance metadata
- A summary section with predicate distribution and confidence statistics

Open this file in any Markdown viewer (GitHub, VS Code, Obsidian, etc.) to
begin the review process.

---

## Current limitations

These are known, intentional limitations of the MVP.  They are not bugs; they
reflect the scope of the current implementation.

- **Lexical similarity only** — candidate generation is based entirely on
  fuzzy string matching of labels and synonyms.  There is no semantic
  understanding of definitions, no embedding-based similarity, and no
  reasoning over ontology hierarchies.

- **Single ontology profile** — each pipeline run maps against one ontology
  profile at a time.  Multi-ontology reasoning (e.g. cross-ontology bridging
  axioms) is not supported.

- **No automated transformation validation** — `custom:requiresTransform`
  mappings flag the need for a value transformation, but the transformation
  itself is not specified, validated, or tested.

- **No SHACL validation** — the pipeline does not validate whether the mapped
  entities conform to the target ontology's SHACL constraints.

- **No SPARQL competency questions** — the pipeline does not run SPARQL
  queries to verify that the mapped data satisfies ontology competency
  questions.

- **SSSOM export is partial** — the TSV export omits several required SSSOM
  metadata fields (mapping set IRI, creator IRI, mapping date in ISO format,
  etc.).

- **No GUI** — the review workflow is entirely file-based.  A web-based
  collaborative review interface is planned for Phase 5.

- **Human review is advisory only** — the `SuggestedAction` recommendations
  are generated by a decision-tree heuristic.  The pipeline does not implement
  an interactive review loop; reviewers use the report to make decisions and
  record them externally.

---

## What is intentionally NOT implemented yet

The following capabilities are architecturally planned but explicitly out of
scope for the MVP:

- **LLM-based semantic understanding** — using large language models to
  reason about term definitions, biological context, and semantic equivalence
  (Phase 2)
- **SHACL validation** — validating that source data conforms to ontology
  shapes after mapping (Phase 3)
- **SPARQL competency questions** — executing ontology competency queries
  against the mapped data (Phase 3)
- **JSON-LD export** — serialising approved mappings as JSON-LD with full
  IRI resolution (Phase 4)
- **RO-Crate packaging** — bundling pipeline outputs as a Research Object
  Crate for FAIR data sharing (Phase 4)
- **Full SSSOM compliance** — generating fully conformant SSSOM mapping set
  files with all required metadata fields (Phase 4)
- **Ontology evolution tracking** — detecting when target ontology terms are
  deprecated, merged, or split, and triggering re-review of affected mappings
  (Phase 6)
- **Multi-ontology reasoning** — reasoning across multiple ontologies
  simultaneously, including cross-ontology bridging axioms (Phase 6)
- **GUI review interface** — a web application for collaborative multi-reviewer
  annotation, disagreement resolution, and audit trail management (Phase 5)

---

## Roadmap

See [docs/roadmap.md](docs/roadmap.md) for the full phased roadmap.

**Phase 1 (current)**: Lexical-similarity MVP with adversarial review,
ranking, validation, and human review report generation.

**Phase 2**: LLM integration — definition-based matching, semantic similarity,
multi-hop hierarchy reasoning.

**Phase 3**: Validation infrastructure — SHACL, SPARQL, transformation testing.

**Phase 4**: Export and standards compliance — full SSSOM, JSON-LD, RO-Crate.

**Phase 5**: Collaborative review — web GUI, multi-reviewer workflow,
disagreement resolution.

**Phase 6**: Ontology evolution — change detection, re-mapping triggers,
version-aware provenance.

---

## Project structure

```
ontology-mapping-co-scientist/
├── src/ontology_mapping_co_scientist/
│   ├── agents/          # Pipeline agent implementations
│   │   ├── source_profiler.py
│   │   ├── ontology_profiler.py
│   │   └── candidate_generator.py
│   ├── io/              # File format loaders and exporters
│   │   ├── csv_loader.py
│   │   ├── openapi_loader.py
│   │   ├── ontology_profile_loader.py
│   │   └── exporters.py
│   ├── models/          # Pydantic data models
│   │   ├── entities.py          (SourceEntity, OntologyTerm)
│   │   ├── mapping_hypothesis.py (MappingHypothesis, Evidence, Provenance, ...)
│   │   └── review.py            (AdversarialReviewResult, HumanReviewAction, ...)
│   ├── pipeline/        # Pipeline orchestration entry point
│   │   └── run_mapping_pipeline.py
│   ├── reports/         # Report generators
│   │   └── markdown_report.py
│   └── scoring/         # Scoring utilities
│       └── lexical_similarity.py
├── examples/
│   ├── ontology_profiles/   # Sample ontology profile YAML files
│   ├── source_csv/          # Sample CSV source files
│   ├── source_openapi/      # Sample OpenAPI JSON source files
│   └── outputs/             # Pipeline output files (git-ignored)
├── scripts/
│   └── run_example.py   # Self-contained example runner
├── docs/
│   ├── architecture.md
│   ├── mapping_hypothesis_model.md
│   ├── agent_roles.md
│   ├── human_in_the_loop.md
│   └── roadmap.md
└── tests/               # Test suite
```

---

## Contributing

Contributions are welcome.  Before submitting a pull request:

1.  Run the test suite: `pytest`
2.  Run the linter: `ruff check src/ scripts/`
3.  Run the type checker: `mypy src/`
4.  Ensure your change is covered by tests where feasible
5.  Update the relevant documentation files if your change affects architecture
    or data models

For significant changes — new agents, new source format support, changes to
the data model — please open an issue first to discuss the design.

---

## License

MIT — see [LICENSE](LICENSE).

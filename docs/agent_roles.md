# Agent Roles

This document describes each agent role in the ontology mapping co-scientist
pipeline.  For each agent it covers: the conceptual role (what a human expert
in this position would do), the current MVP implementation, the inputs and
outputs, the future LLM integration point, and the key decisions and heuristics
currently used.

---

## 1. OrchestratorAgent

### Conceptual role

A project coordinator who sequences the work of all other agents, ensures that
data flows correctly between stages, handles errors gracefully, writes output
files, and produces the final status report.

In a human team, this role would be played by a senior scientist or data
manager who coordinates the mapping workflow: briefing specialists, collecting
their outputs, escalating problems, and communicating results to stakeholders.

### Current implementation

The orchestration logic is implemented as the `run_pipeline()` function in
`pipeline/run_mapping_pipeline.py`.  It is not yet a separate class.  It:
- Instantiates all agents
- Calls them in order
- Handles logging at each stage
- Assembles the result dict
- Calls the exporters and report generator
- Returns a summary

### Inputs

- `source_filepath: str | Path`
- `ontology_filepath: str | Path`
- `output_dir: str | Path`
- `pipeline_run_id: str | None`
- `verbose: bool`

### Outputs

- A result dict with paths to output files and summary statistics
- Side effects: writes three files to `output_dir`

### Future LLM integration point

In Phase 2, the orchestrator could be augmented with LLM-based planning:
deciding which agents to run, in which order, and with which parameters, based
on a natural-language description of the mapping task and the source data.

### Key decisions

- Pipeline run ID: generated as UUID4 if not provided
- Output file naming: `<source_stem>_<UTC_timestamp>_<type>.<ext>`
- Logging level: controlled by the `verbose` flag
- Error handling: currently propagates exceptions; production use should add
  per-stage error recovery

---

## 2. SourceProfilerAgent

### Conceptual role

A data engineer or bioinformatician who examines a source data file, identifies
all the entities (fields, columns, parameters) it contains, characterises their
types and representative values, and produces a structured summary suitable for
downstream mapping work.

In a human team, this person would look at a CSV file or API specification and
fill in a spreadsheet: "column name", "data type", "example values",
"description from schema".

### Current implementation

`agents/source_profiler.py` — wraps the `io/` loaders with:
- Format auto-detection by file extension (`.csv` → `csv_loader`,
  `.json` → `openapi_loader`)
- Logging of entity counts
- A `summarize()` method that counts entities by datatype and source type

### Inputs

- `filepath: str | Path` — CSV file or OpenAPI JSON file

### Outputs

- `list[SourceEntity]` — one `SourceEntity` per column (CSV) or schema
  property (OpenAPI)

### Future LLM integration point

In Phase 2, the SourceProfilerAgent could use an LLM to:
- Generate richer descriptions for fields that lack formal descriptions
- Infer the semantic domain of a field from its example values
- Suggest normalisation or pre-processing steps
- Detect potential ontology domains to search (e.g. "this looks like a
  clinical phenotype field, try HPO")

### Key decisions and heuristics

**CSV loader**:
- One `SourceEntity` per column; a column named `description` is treated as a
  file-level description hint, not a mappable entity
- Datatype is inferred from up to all column values: numeric if all parseable
  as `float`, boolean if all in `{true, false, yes, no, 1, 0}`, else string
- Up to three non-empty example values are collected per column
- `entity_id` convention: `csv:<stem>.<column_name_lowercased_underscored>`

**OpenAPI loader**:
- One `SourceEntity` per property in each schema under `components/schemas`
  (OpenAPI 3.x) or `definitions` (Swagger 2.x)
- `description` and `example` fields from the schema are preserved
- Nested `$ref` objects are flagged in `extra_context["ref"]` but not resolved
- `entity_id` convention: `api:<schema_name>.<prop_name>`

---

## 3. OntologyProfilerAgent

### Conceptual role

An ontology engineer who reads an ontology file, extracts all relevant terms,
and builds an efficient lookup structure so that candidate terms can be
retrieved quickly during mapping.

In a human team, this person would prepare a curated list of candidate terms
from the target ontology, organised by label and synonym, and provide it to
the mapping scientist.

### Current implementation

`agents/ontology_profiler.py` — wraps the `ontology_profile_loader` with:
- In-memory normalised label index (`dict[str, OntologyTerm]`)
- In-memory synonym index (`dict[str, list[OntologyTerm]]`)
- A `get_candidates_for_label(label, top_k)` method
- A `summarize()` method

The profiler works with pre-curated ontology profile YAML files, not with full
OWL/OBO ontologies.  The profile format is a lightweight subset that contains
the terms most relevant to a specific mapping task.

### Inputs

- `filepath: str | Path` — YAML or JSON ontology profile file

### Outputs

- `list[OntologyTerm]` — all terms from the profile
- Internal indexes used by `get_candidates_for_label()`

### Future LLM integration point

In Phase 2, the OntologyProfilerAgent could:
- Load full OWL ontologies via `owlready2` or `rdflib`
- Use LLM embeddings to compute dense representations of all term labels and
  definitions, enabling embedding-based candidate retrieval
- Dynamically expand the term pool by querying OLS (Ontology Lookup Service)
  or BioPortal for additional candidate terms based on the source entity profile
- Detect missing terms in the profile and flag them for ontology engineer review

### Key decisions and heuristics

- Label normalisation: lowercase, underscore/hyphen → space, collapse spaces
  (via `scoring/lexical_similarity.normalize_label()`)
- Duplicate normalised labels: last-wins with a warning logged
- The profile file must supply `ontology_id` and `ontology_source` at the
  top level as defaults for terms that omit those fields
- Terms with missing `term_id` or `label` are skipped with a stderr warning

---

## 4. CandidateGeneratorAgent

### Conceptual role

A mapping scientist who systematically compares each source entity against all
candidate ontology terms and proposes the most plausible matches, along with
a confidence score and the evidence that supports each proposal.

In a human team, this person would work through a spreadsheet of source fields,
search an ontology browser for each one, and fill in the top 5 candidates with
their match type (exact, close, broad, narrow) and a brief justification.

### Current implementation

`agents/candidate_generator.py` — uses `rapidfuzz` fuzzy string matching:

1. For each `SourceEntity`, calls `find_best_matches(entity.label, term_labels, top_k)`
   to get the top-k preferred-label matches.
2. Also computes similarity against all ontology synonyms to find synonym-only
   matches not covered by preferred labels.
3. Merges and deduplicates candidates; sorts by `max(lex_score, syn_score)`.
4. For each candidate, builds `Evidence` objects (lexical and/or synonym).
5. Computes aggregate confidence via `compute_aggregate_confidence()`.
6. Assigns a predicate via `label_to_predicate(best_score)` (score-based
   heuristic: ≥0.90 → exactMatch, ≥0.70 → closeMatch, ≥0.50 → broadMatch,
   else relatedMatch).
7. If no candidates meet `min_confidence`, emits a `NO_MAPPING` hypothesis.

### Inputs

- `source_entities: list[SourceEntity]`
- `ontology_terms: list[OntologyTerm]`
- `pipeline_run_id: str | None`
- Configuration: `top_k=5`, `min_confidence=0.0`

### Outputs

- `list[MappingHypothesis]` — up to `top_k` hypotheses per entity, or one
  `NO_MAPPING` hypothesis if no candidate meets the threshold

### Future LLM integration point

In Phase 2, candidate generation could be augmented with:
- **Embedding-based retrieval**: dense vector similarity between source entity
  descriptions/examples and ontology term definitions
- **Definition-based matching**: asking an LLM to compare a source entity
  description with an ontology term definition and score their semantic overlap
- **Multi-hop reasoning**: traversing the ontology hierarchy to find candidates
  that are not lexically similar but are semantically related via parent/child
  terms
- **Example-value-based inference**: using source entity example values to
  infer the ontological domain (e.g. values "C57BL/6", "BALB/c" → mouse strain)

### Key decisions and heuristics

- `rapidfuzz.fuzz.token_sort_ratio`, `partial_ratio`, and `token_set_ratio`
  are all computed; the maximum is used (this handles word-order differences
  and partial containment relationships)
- Synonym scores are computed against the normalised synonym string
- Aggregate confidence = `0.7 * lex_score + 0.3 * syn_score` when both are
  present; the dominant score when only one is present (exact coefficients are
  in `scoring/evidence_scoring.py`)
- `mapping_id` format: `map_<safe_entity_id>_<safe_term_id>_<rank_index>` where
  unsafe characters are replaced with underscores
- Provenance `method` is `"lexical_similarity_v1"` for all hypotheses from this
  agent

---

## 5. AdversarialReviewerAgent

### Conceptual role

A sceptical peer reviewer who looks for reasons a proposed mapping might be
wrong, misleading, or poorly supported.  The adversarial reviewer's job is not
to approve mappings but to find the weakest points in every proposal.

In a human team, this role is played by someone who asks questions like: "Why
are you confident this is exact match and not just close match?", "What if
the label is the same but the definition is different?", "Have you checked that
the target term is not deprecated?".

### Current implementation

Implemented as the `_adversarial_review()` function in
`pipeline/run_mapping_pipeline.py` (to be extracted to
`agents/adversarial_reviewer.py` in a future refactor).

Current checks:
- **Low confidence** (< 0.40 → high severity; < 0.70 → medium)
- **Missing definition** on the target term (medium severity)
- **Synonym-only match** — no preferred-label evidence (low severity)
- **NO_MAPPING result** (high severity — requires human decision)
- **Ambiguous short label** — source label is ≤ 4 characters (low severity)

### Inputs

- `hypothesis: MappingHypothesis`

### Outputs

- `AdversarialReviewResult` containing zero or more `AdversarialFlag` objects
  and an `overall_severity` and `recommendation`

### Future LLM integration point

In Phase 2, the adversarial reviewer could use an LLM to:
- Compare the source entity description with the target term definition and
  identify specific semantic discrepancies
- Check whether the source entity's example values are consistent with the
  ontology term's expected value range
- Identify whether the proposed predicate is logically consistent with the
  hierarchy relationship between source and target
- Generate natural-language critiques of the mapping proposal

### Key decisions and heuristics

- Severity thresholds are configurable but currently hard-coded
- `overall_severity` is the maximum severity across all flags
- `recommendation` is `"reject"` for high-severity, `"review"` for medium,
  `"proceed"` for clean or low-only
- Checks are additive: multiple flags can be raised for a single hypothesis

---

## 6. RankingAgent

### Conceptual role

A senior mapping scientist who looks at all candidate hypotheses for each
source entity and decides which one deserves the most attention during human
review.  The top-ranked hypothesis is the pipeline's primary recommendation.

### Current implementation

Implemented as the `_rank_hypotheses()` function in
`pipeline/run_mapping_pipeline.py`.

Algorithm:
1. Group hypotheses by `source_entity.entity_id`
2. Within each group, sort by `(is_no_mapping, -confidence, mapping_id)`
   - `NO_MAPPING` hypotheses always rank last
   - Among non-NO_MAPPING hypotheses, rank by confidence descending
   - Tie-break by `mapping_id` for determinism
3. Assign integer ranks 1..n and return the full list

### Inputs

- `list[MappingHypothesis]` (unranked)

### Outputs

- `list[MappingHypothesis]` (with `rank` field populated)

### Future LLM integration point

In Phase 2, ranking could incorporate:
- Semantic evidence scores from embedding agents
- Ontology hierarchy scores (prefer narrower matches over broader matches
  when the specificity is appropriate)
- A learned ranker trained on historical human review decisions
- A composite ranking function with configurable weights per evidence type

### Key decisions

- `NO_MAPPING` always ranks last so that the review report's top slot is
  never occupied by a "nothing found" result
- Deterministic tie-breaking via `mapping_id` ensures reproducibility
- Ranking is per-entity, not global

---

## 7. ValidationAgent

### Conceptual role

A quality assurance scientist who runs a checklist of automated tests on every
proposed mapping before it goes to human review.  The validator does not make
semantic judgements; it checks structural and quantitative properties.

### Current implementation

Implemented as the `_validate_hypothesis()` function in
`pipeline/run_mapping_pipeline.py`.

Current checks:
- Confidence in `[0.0, 1.0]` (always true given Pydantic, but explicit)
- Non-`NO_MAPPING` hypotheses should have at least one evidence item
- Rank-1 hypothesis should not be `NO_MAPPING` (unless it is the only
  candidate)

Validation outcome rules:
- Any failed check → `validation_status = "failed"`, failure description
  appended to `warnings`
- Only non-fatal issues → `validation_status = "warning"`
- No issues → `validation_status = "passed"`

### Inputs

- `hypothesis: MappingHypothesis` (mutated in-place)

### Outputs

- Modified `hypothesis.validation_status`
- Modified `hypothesis.warnings` (appended to)

### Future LLM integration point

In Phase 3, the validation agent will be extended with:
- **SHACL validation**: checking whether the source entity's datatype and
  example values conform to the target ontology term's SHACL shape constraints
- **SPARQL competency questions**: executing SPARQL queries that the mapped
  data is expected to answer correctly
- **Value transformation validation**: verifying that a stated transformation
  (e.g. unit conversion) produces values within the expected range
- **Ontology consistency checks**: verifying that the proposed predicate is
  logically consistent with the ontology's declared relationships

### Key decisions

- Validation modifies hypotheses in-place rather than returning new objects,
  to minimise object creation overhead in the MVP
- Failed validation does not remove a hypothesis from the pipeline; it flags
  it for mandatory human review

---

## 8. HumanReviewAgent

### Conceptual role

A scientific communicator who takes all the technical output of the pipeline
and translates it into a structured package that a domain scientist can
actually act on.  This includes selecting the most important information,
framing it in terms the reviewer will understand, and making a concrete
recommendation.

### Current implementation

Implemented as `_build_review_packets()` and `_suggest_action()` in
`pipeline/run_mapping_pipeline.py`.

`_suggest_action()` uses a decision tree:
1. `NO_MAPPING` → `CREATE_NEW_TERM`
2. Any high-severity flag and low confidence → `REJECT`
3. `broad_narrow_ambiguity` flag → `CHANGE_PREDICATE` (to `closeMatch`)
4. Clean + confidence ≥ 0.85 → `APPROVE`
5. Low-or-clean + confidence ≥ 0.70 → `APPROVE`
6. `synonym_only_match` flag → `REQUEST_MORE_EVIDENCE`
7. Otherwise → `REQUEST_MORE_EVIDENCE`

`_build_review_packets()` creates one packet per source entity containing:
- Serialised top hypothesis (as dict for the report renderer)
- Serialised alternative hypotheses
- Serialised suggested action
- Aggregated warnings from both the hypothesis and adversarial result
- Original model objects for downstream Python use

### Inputs

- `list[MappingHypothesis]` (ranked and validated)
- `dict[str, AdversarialReviewResult]`

### Outputs

- `list[dict]` — one review packet per source entity

### Future LLM integration point

In Phase 2, the HumanReviewAgent could:
- Generate natural-language rationales for each recommendation that explain
  the evidence in domain-appropriate language
- Identify patterns across multiple mappings and surface them as batch
  recommendations ("All 12 'strain'-type fields appear to map to MouseStrain
  or GeneticBackground — would you like to approve all at once?")
- Draft reviewer notes for high-confidence mappings that the human can accept
  or edit

---

## Planned but not yet implemented as separate agents

### DomainScientistReviewer (planned, Phase 2)

A specialised reviewer agent with deep knowledge of a scientific domain
(e.g. mouse phenotyping, clinical oncology, pharmacogenomics).  In the current
MVP, this role is approximated by the heuristic `_suggest_action()` function.
In Phase 2, this agent would use an LLM fine-tuned or prompted with domain
knowledge to provide semantically informed review recommendations.

### OntologyEngineerReviewer (planned, Phase 2)

A reviewer agent that understands formal ontology structure: class hierarchies,
property domains and ranges, OWL axioms, and SKOS relationship semantics.  It
would flag cases where the proposed predicate is inconsistent with the ontology
hierarchy and suggest corrections grounded in formal logic.

### DataAPIEngineerReviewer (planned, Phase 2)

A reviewer agent that understands data types, API contracts, serialisation
formats, and value transformations.  It would flag type incompatibilities,
suggest `custom:requiresTransform` predicates where unit conversions or string
normalisations are needed, and generate transformation specifications.

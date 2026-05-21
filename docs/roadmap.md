# Development Roadmap

Status key: `[x]` done · `[~]` in progress · `[ ]` not started

---

## Phase 1 — MVP `v0.1.0` ✅ COMPLETE

**Goal**: Working end-to-end pipeline on lexical similarity alone.

- [x] Pydantic `MappingHypothesis` model with provenance, evidence, review state
- [x] `SourceProfilerAgent` — CSV and OpenAPI 3.x
- [x] `OntologyProfilerAgent` — YAML profiles, label/synonym index
- [x] `CandidateGeneratorAgent` — rapidfuzz WRatio lexical similarity
- [x] `AdversarialReviewerAgent` — 9 heuristic flag types
- [x] `RankingAgent` — adversarial-penalty-adjusted scoring
- [x] `ValidationAgent` — basic consistency checks
- [x] `HumanReviewAgent` — suggested action logic + review packets
- [x] `OrchestratorAgent` — full pipeline wiring
- [x] Exporters: JSON, SSSOM-inspired TSV, Markdown review report
- [x] 114 pytest tests
- [x] Example data: mouse HCM (CSV + OpenAPI + ontology profile)
- [x] `python scripts/run_example.py` produces all three output types

---

## Phase 1.5 — Scoring & Format Improvements `v0.1.5` ✅ COMPLETE

*Improvements implemented after MVP, before LLM integration.*

**Scoring**
- [x] S1 — Definition-based similarity (TF-IDF; sentence-transformers optional)
- [x] S2 — Unit-aware scoring (regex unit extractor; high-severity mismatch flag)
- [x] S3 — Cross-field synonym expansion (45-entry biomedical abbreviation dictionary)

**Source formats**
- [x] F1 — JSON Schema loader (`$ref`, `allOf/anyOf`, nested dot-notation, depth limit)
- [x] F2 — RDF/OWL ontology loader (`rdflib`; optional dep, clean `ImportError`)

**Export & standards**
- [x] E1 — Full SSSOM compliance (YAML header, full SKOS IRIs, `semapv:` justification)

**Human review workflow**
- [x] W1 — Review ledger (`ReviewDecision` YAML store, `omcs-review` CLI)
- [x] W2 — Re-run mode (`--ledger` flag; approved entities skip re-generation)

**LLM (partial)**
- [x] L1 — `LLMAdversarialReviewerAgent` (Anthropic SDK; heuristic fallback)

**Evolution (not yet)**
- [ ] H1 — Ontology version tracking (`evolution/version_tracker.py`)
- [ ] H2 — Re-mapping trigger on ontology change (`evolution/remapping_trigger.py`)

Total tests: **183 passing**

---

## Phase 2 — LLM Integration `v0.2.0` 🔴 IN PROGRESS

**Goal**: Replace lexical heuristics with LLM semantic reasoning at every pipeline stage where it adds value.

### Candidate generation
- [x] L1 `LLMAdversarialReviewerAgent` — argue against mappings *(done in Phase 1.5)*
- [ ] L2 `LLMCandidateGeneratorAgent` — score (source description ↔ ontology definition) pairs with Claude; emit `Evidence(evidence_type="llm_semantic_similarity")`; fall back to lexical
- [ ] L3 `LLMOntologyEngineerReviewerAgent` — check logical consistency: predicate appropriateness, domain/range, class/property compatibility
- [ ] L4 `LLMDomainScientistReviewerAgent` — evaluate scientific plausibility in a user-specified domain context
- [ ] L5 Cost tracker — record token usage per pipeline run; report estimate before and actual after

### Prompt infrastructure
- [ ] `prompts/` module: versioned, templated prompt strings so prompts can be audited and iterated independently of agent code
- [ ] Prompt hash stored in `Provenance.extra` for reproducibility
- [ ] Chain-of-thought parsing: extract structured evidence from LLM reasoning steps

### Fallback chain
- [ ] Unified fallback: LLM → definition TF-IDF → lexical → `custom:noMapping` — always produces a result

---

## Phase 3 — Validation Infrastructure `v0.3.0` 🔴 NOT STARTED

**Goal**: Move from syntactic to semantic validation of mapping correctness.

### Core validation
- [ ] V1 `DatatypeValidator` — check source `datatype` against target term's `rdfs:range`; emit `ValidationStatus.WARNING` on mismatch
- [ ] V2 `TransformationValidator` — for `custom:requiresTransform` mappings, test that the specified transformation preserves data integrity on example values; requires `required_conditions` to specify the transform
- [ ] V3 `UnitConsistencyValidator` — full unit registry via `pint`; replaces the regex-based unit extractor for mappings where both sides have physical units

### SHACL
- [ ] V4 `SHACLValidationMixin` — load SHACL shapes alongside ontology profiles; validate that accepted mappings do not violate `sh:class`, `sh:datatype`, `sh:minCount`, `sh:maxCount` constraints; uses `pyshacl`
- [ ] `examples/shacl/` — example shapes graphs for the mouse HCM and preclinical pharmacology profiles

### SPARQL
- [ ] V5 `SPARQLCompetencyAgent` — define competency questions (CQs) as SPARQL ASK/SELECT queries; construct a small test RDF graph from accepted mappings; run CQs and report pass/fail
- [ ] `examples/competency_questions/` — starter CQ library for common preclinical mapping scenarios

### Validation summary
- [ ] `ValidationAgent.generate_full_report()` — structured report combining all validator results per hypothesis; feeds into the Markdown review report

---

## Phase 4 — Export & Standards `v0.4.0`

**Goal**: Outputs interoperable with the semantic web and FAIR data ecosystem.

- [x] E1 Full SSSOM compliance *(done in Phase 1.5)*
- [ ] E2 JSON-LD export — serialize accepted mappings with proper `@context`; load directly into RDF triplestores
- [ ] E3 RO-Crate packaging — wrap a full pipeline run (inputs, outputs, provenance) as a Research Object Crate
- [ ] E4 OWL axiom generation — for `skos:exactMatch`, optionally emit `owl:equivalentClass` / `owl:equivalentProperty`
- [ ] E5 Bridging ontology export — lightweight OWL file formalizing accepted mappings

---

## Phase 5 — Collaborative Review Interface `v0.5.0`

**Goal**: Structured multi-reviewer workflows beyond the CLI ledger.

- [x] W1 Review ledger CLI *(done in Phase 1.5)*
- [ ] FastAPI backend — serve review packets as JSON; accept decisions via REST
- [ ] Minimal web UI — per-entity review form (approve/reject/change/request)
- [ ] Role-based review forms — separate views for Domain Scientist, Ontology Engineer, Data Engineer
- [ ] Multi-reviewer consensus — require N approvals before a mapping is accepted
- [ ] Review versioning — full history of each mapping decision
- [ ] Conflict resolution — escalate disagreements to a designated arbiter

---

## Phase 6 — Ontology Evolution `v1.0.0`

**Goal**: Keep accepted mappings correct as ontologies and source schemas change.

- [ ] H1 Ontology version tracking — diff two profile snapshots; emit `ChangeReport`
- [ ] H2 Re-mapping trigger — flag accepted mappings whose target term changed; reset `human_review_status` to `awaiting_review`
- [ ] H3 Deprecation handler — when a target term is deprecated, find replacement candidates automatically
- [ ] H4 Semantic drift detection — use LLMs to compare old and new term definitions; flag meaningful conceptual shifts
- [ ] H5 Changelog integration — link mapping changes to ontology release notes

---

## Design Principles (all phases)

1. Backward-compatible data models — new fields are additive; existing pipelines never break
2. Graceful degradation — if LLM/SHACL/rdflib is unavailable, fall back silently with a logged warning
3. Provenance at every step — every automated decision records who made it, when, and how
4. Human authority — no phase removes the human from the final decision
5. Small, independently testable components — each feature can be exercised without running the full pipeline
6. Scientific honesty — never present a mapping as more certain than the evidence warrants

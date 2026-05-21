# Development Roadmap

This document describes the planned evolution of the Ontology Mapping Co-Scientist. The MVP (v0.1.0) establishes the architecture and a working lexical-similarity baseline. Each subsequent phase builds on that foundation without breaking it.

---

## Phase 1 — MVP (Current: v0.1.0)

**Goal**: Establish the architecture, data models, and a functional end-to-end pipeline using only lexical similarity.

### Delivered
- Pydantic-based `MappingHypothesis` model with full provenance, evidence, and review state
- Source profiler for CSV and OpenAPI 3.x schemas
- Ontology profiler with label and synonym indexing
- Candidate generator using `rapidfuzz` WRatio lexical similarity
- Adversarial reviewer with 9 heuristic flag types
- Ranking agent with adversarial-penalty-adjusted scoring
- Validation agent with basic consistency checks
- Human review agent with suggested action logic
- Orchestrator wiring all agents together
- JSON, SSSOM-inspired TSV, and Markdown report exporters
- 114 pytest tests
- Example data: mouse HCM phenotyping context (CSV + OpenAPI + ontology profile)
- `python scripts/run_example.py` produces all three output types

### Known limitations of Phase 1
- Lexical similarity only — no semantic understanding
- No synonym expansion beyond what is in the profile
- No definition-based matching
- No SHACL or SPARQL validation
- Human review is output-only (no interactive interface)
- SSSOM output is inspired by but not fully compliant with the SSSOM standard
- Only CSV and OpenAPI sources supported

---

## Phase 2 — LLM Integration (Target: v0.2.0)

**Goal**: Replace or augment lexical heuristics with LLM-based semantic reasoning.

### Planned
- `LLMCandidateGeneratorAgent`: uses LLM to assess semantic similarity between source field descriptions and ontology term definitions; falls back to lexical when LLM unavailable
- `LLMAdversarialReviewerAgent`: prompts an LLM to argue against each mapping from a domain scientist perspective
- `LLMOntologyEngineerReviewerAgent`: checks logical consistency of proposed mappings
- `LLMDomainScientistReviewerAgent`: evaluates scientific plausibility
- Structured prompts with chain-of-thought evidence extraction
- LLM output parsed into `Evidence` objects — the LLM's reasoning becomes traceable
- Fallback chain: LLM → lexical → no-mapping (always produces a result)
- Cost estimation per pipeline run

### Extension points already in the codebase
- Each agent class is independently replaceable
- `Evidence.source` field can record LLM model/version
- `Provenance.method` distinguishes lexical vs. LLM approaches
- `CandidateGeneratorAgent.generate_candidates` signature is stable

---

## Phase 3 — Validation Infrastructure (Target: v0.3.0)

**Goal**: Move beyond syntactic checks to semantic validation.

### Planned
- **SHACL validation**: load SHACL shapes alongside ontology profiles; validate that proposed mappings do not violate domain/range constraints
- **SPARQL competency questions**: define a set of competency questions that must be answerable given the accepted mappings; run them against a test RDF graph
- **Transformation tests**: for `custom:requiresTransform` mappings, validate that the specified transformation preserves data integrity on example values
- **Unit consistency checker**: detect unit mismatches using a unit registry (e.g., `pint`)
- **Datatype validator**: verify that the source datatype is compatible with the target term's `rdfs:range`

### `ValidationAgent` extension
The existing `ValidationAgent` has a `validate_hypothesis` method designed to be extended. Phase 3 will add:
```python
class SHACLValidationMixin:
    def validate_with_shacl(self, hypothesis, shapes_graph): ...

class SPARQLValidationMixin:
    def validate_with_sparql(self, hypothesis, endpoint): ...
```

---

## Phase 4 — Export and Standards Compliance (Target: v0.4.0)

**Goal**: Produce outputs that are interoperable with the broader semantic web and data management ecosystem.

### Planned
- **Full SSSOM compliance**: generate valid SSSOM TSV with all required metadata headers, correct predicate IRIs, and a YAML header block
- **JSON-LD export**: serialize accepted mappings as JSON-LD with proper `@context`; enable direct loading into RDF triplestores
- **RO-Crate packaging**: wrap the full mapping run (inputs, outputs, provenance) as a Research Object Crate for FAIR data compliance
- **OWL axiom generation**: for `skos:exactMatch` mappings, optionally generate `owl:equivalentClass` or `owl:equivalentProperty` axioms
- **Bridging ontology export**: generate a lightweight bridging ontology that formalizes the accepted mappings

---

## Phase 5 — Collaborative Review Interface (Target: v0.5.0)

**Goal**: Support structured multi-reviewer workflows.

### Planned
- Web-based review interface (FastAPI backend + simple frontend) for viewing and acting on review packets
- Role-based review forms: Domain Scientist, Ontology Engineer, Data Engineer perspectives
- Multi-reviewer consensus: require N reviewers before accepting a high-stakes mapping
- Review versioning: track changes to mapping decisions over time
- Notification system: alert reviewers when new candidates are ready
- Conflict resolution workflow: when reviewers disagree, escalate to a designated decision maker
- Integration with GitHub Issues / JIRA for tracking new ontology term requests

---

## Phase 6 — Ontology Evolution Tracking (Target: v1.0.0)

**Goal**: Maintain mapping quality as ontologies and source schemas change.

### Planned
- Change detection: when a new version of an ontology or source schema is loaded, detect which mappings may be affected
- Re-mapping triggers: automatically flag accepted mappings for re-review when their source or target terms change
- Mapping versioning: track the full history of each mapping hypothesis, including all revisions
- Deprecation handling: when a target term is deprecated, find replacement candidates automatically
- Semantic drift detection: use LLMs to compare old and new term definitions and flag meaningful changes
- Changelog integration: link mapping changes to ontology release notes

---

## Principles Guiding All Phases

1. **Backward compatibility of data models**: the `MappingHypothesis` schema should be stable; new fields are additive
2. **Graceful degradation**: if an advanced feature (LLM, SHACL) is unavailable, the system falls back to what is available
3. **Provenance at every step**: every automated decision records what made it
4. **Human authority**: no phase removes the human from the final decision; automation narrows the search space, it does not replace judgement
5. **Small, testable components**: each new feature should be independently testable without running the full pipeline
6. **Scientific honesty**: the system must never present a mapping as more certain than the evidence warrants

---

## Contributing to the Roadmap

If you are using this system in a domain with specific requirements not covered here, please open an issue describing:
- Your source schema type(s)
- Your target ontology or ontologies
- The mapping use case (data integration, annotation, federated query, etc.)
- Which phase 2–6 features would be most valuable to you

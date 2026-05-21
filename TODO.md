# Improvement Backlog

Tracked improvements for the Ontology Mapping Co-Scientist.
Each item includes status, priority, owning module, and implementation notes.

---

## Scoring & Matching

### S1 — Definition-based similarity
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../scoring/definition_similarity.py`, `agents/candidate_generator.py`  
**Notes**: Add TF-IDF scoring against ontology term definitions (always available).
Optionally use `sentence-transformers` (`all-MiniLM-L6-v2`) when installed.
Output is a new `Evidence` object with `evidence_type="definition_tfidf"` or
`evidence_type="semantic_embedding"`. Combine with lexical score in
`compute_aggregate_confidence`.

### S2 — Unit-aware scoring
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../scoring/unit_extractor.py`, `agents/adversarial_reviewer.py`  
**Notes**: Extract unit strings from labels/descriptions (`ng_ml`, `g_dl`, `mmol_l`, etc.)
using regex. Compare source and target units. Flag unit mismatch as
`custom:requiresTransform` instead of the lexical predicate. Add
`unit_mismatch` adversarial flag with severity=high when units conflict.

### S3 — Cross-field synonym expansion
**Status**: [x] complete  
**Priority**: medium  
**Files**: `src/.../scoring/synonym_expander.py`, `agents/candidate_generator.py`  
**Notes**: Ship a bundled `data/biomedical_synonyms.tsv` (curated subset: common
clinical/PK/tox abbreviations — AUC, ALT, WBC, Cmax, etc.) so the generator
can expand source entity labels before scoring. No external API call required.

---

## Source Formats

### F1 — JSON Schema loader
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../io/json_schema_loader.py`, `agents/source_profiler.py`  
**Notes**: Parse `$schema`, `properties`, `$defs`/`definitions`, `allOf`/`anyOf`.
Recurse into nested objects up to depth 3. Each property becomes a
`SourceEntity` with `source_type="json_schema"`.

### F2 — RDF/OWL ontology loader
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../io/rdf_ontology_loader.py`, `agents/ontology_profiler.py`  
**Notes**: Use `rdflib` to load OWL/Turtle/RDF-XML files and SPARQL endpoints.
Extract `rdfs:label`, `skos:altLabel`, `skos:definition`, `skos:prefLabel`,
`rdfs:subClassOf`, `rdfs:domain`, `rdfs:range`. Replaces need for hand-crafted
YAML profiles for real ontologies (OBI, UBERON, CHEBI, etc.).

---

## Export & Standards

### E1 — Full SSSOM compliance
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../io/exporters.py`, `src/.../io/sssom_exporter.py`  
**Notes**: Add proper SSSOM YAML metadata header block with `mapping_set_id`,
`mapping_set_version`, `license`, `creator_id`, correct SKOS predicate IRIs
(full URIs). Output should pass `sssom-utils validate`. Keep the existing
simplified TSV exporter but add `export_to_sssom_compliant_tsv()` as a
separate function.

---

## Human Review Workflow

### W1 — Review ledger
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../review_ledger/ledger.py`, `src/.../review_ledger/cli.py`  
**Notes**: Persist human review decisions to a YAML ledger file
(`mapping_review_ledger.yaml`). CLI command: `omcs-review accept <mapping_id>`,
`omcs-review reject <mapping_id> --note "..."`, `omcs-review status`.
Ledger stores: mapping_id, action, reviewer, timestamp, note, predicate_override.

### W2 — Re-run mode (skip approved mappings)
**Status**: [x] complete  
**Priority**: medium  
**Files**: `agents/orchestrator.py`, `pipeline/run_mapping_pipeline.py`  
**Notes**: Add `--ledger` flag to pipeline. Before generating candidates, check the
ledger for already-approved/rejected mapping_ids. Skip those source entities
or carry forward the human decision. Print a summary of skipped vs. new at
the end.

---

## LLM Integration

### L1 — LLM-backed adversarial reviewer
**Status**: [x] complete  
**Priority**: high  
**Files**: `src/.../agents/llm_adversarial_reviewer.py`  
**Notes**: Drop-in replacement for `AdversarialReviewerAgent`. Accepts an optional
`llm_client` (Anthropic SDK). If client is None, falls back to heuristic
reviewer. Sends a structured prompt asking the LLM to argue against the
proposed mapping. Parses response into `AdversarialFlag` objects. Records
model name + prompt hash in `Provenance.extra`. Use `claude-haiku-4-5` as
default (low cost). Requires `ANTHROPIC_API_KEY` env var.

---

## Mapping History & Evolution

### H1 — Ontology version tracking
**Status**: [ ] not started  
**Priority**: medium  
**Files**: `src/.../evolution/version_tracker.py`  
**Notes**: Compare two ontology profile snapshots (YAML) and detect:
added terms, removed terms, changed labels/definitions/synonyms.
Output a `ChangeReport` Pydantic model listing affected mappings.
Depends on W1 (review ledger) being complete.

### H2 — Re-mapping trigger on ontology change
**Status**: [ ] not started  
**Priority**: medium  
**Files**: `src/.../evolution/remapping_trigger.py`  
**Notes**: Given a `ChangeReport` and a review ledger, flag all approved mappings
whose target term changed. Set their `human_review_status` back to
`awaiting_review` and add a reviewer note explaining what changed.

---

## Legend
- [ ] not started
- [~] in progress
- [x] complete

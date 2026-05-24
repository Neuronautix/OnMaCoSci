# Architecture Decision: Split Ontology Alignment and Schema Mapping into Two Distinct Tools

**Date**: 2024-06  
**Status**: Accepted  
**Context**: Mapping Co-Scientist monorepo refactor

---

## 1. The Problem with a Single "Mapping Tool"

The original repository was conceived as an "Ontology Mapping Co-Scientist" — a system for mapping anything to anything using a shared agentic pipeline. In practice, this conflated two fundamentally different intellectual tasks:

| Dimension | Ontology Alignment | Schema Mapping |
|-----------|-------------------|----------------|
| **Core question** | Does concept X correspond to ontology entity Y? | How should field X in schema A be represented in schema B? |
| **Output type** | Knowledge claim (semantic assertion) | Transformation specification (operational rule) |
| **Primary artefact** | Mapping predicate (skos:closeMatch, etc.) | Transformation rule (copy, rename, convert, assign) |
| **Domain** | Formal ontology engineering, semantic web | Data engineering, ETL, schema interoperability |
| **Export format** | SSSOM, JSON-LD, RDF | YAML mapping spec, JSONata, RML |
| **Validation** | Semantic checks, SHACL, OWL reasoning | Datatype checks, unit conversion, round-trip tests |
| **Error type** | Ontological mis-classification, hierarchy violation | Data loss, type mismatch, unit error, path error |
| **Human reviewer** | Ontology engineer, domain scientist | Data engineer, integration developer |
| **Failure mode** | Over-claiming exactMatch or equivalentClass | Silent information loss, broken transformation |

Treating these as the same tool produces:

1. **Misleading output**: a schema field mapping might accidentally use `skos:narrowMatch` when it should express `rename + datatype_conversion`.
2. **Wrong validation**: running OWL hierarchy checks on a CSV-to-JSON field mapping is meaningless.
3. **Wrong exports**: generating SSSOM for a pure schema transformation misleads downstream consumers about ontological grounding.
4. **Wrong escalation**: the human-in-the-loop review questions differ — "Is this the right ontology class?" vs. "Will this transformation lose data?"

---

## 2. Why They Share an Agentic Core

Despite their differences, both tools follow the same *process architecture*:

```
Input Profiling
    → Candidate Generation (multiple hypotheses)
        → Competing Review (specialist agents)
            → Adversarial Review (critic agent)
                → Ranking
                    → Human-in-the-Loop Gate
                        → Validation
                            → Export
```

This is the **shared agentic workflow** that belongs in `mapping_co_scientist.shared`. Neither tool reimplements this process — they specialise it:

- **Ontology-align** uses semantic profilers, SKOS-based candidate generation, ontology validation, and SSSOM export.
- **Schema-align** uses field profilers, transformation-aware candidate generation, datatype/unit/cardinality validation, and YAML mapping spec export.

The shared core provides:
- Base evidence, provenance, review, and confidence models
- Abstract base agent interface (`BaseAgent`)
- LLM provider interface (`LLMProviderInterface`) and `MockLLMProvider`
- Ranking utilities
- Common serialisation (JSON read/write)
- Abstract Markdown report base

---

## 3. The Critical Conceptual Boundary

### An ontology mapping hypothesis answers:

> "Does source concept X correspond semantically to ontology entity Y, and with what ontological relation?"

**Example**:
```
source: csv:strain
target: hcm:GeneticBackground
relation: skos:narrowMatch
warning: "'strain' is narrower than GeneticBackground, which also includes genotype and breeding history."
```

This is a **knowledge claim**. It can be wrong in an ontological sense. It requires an ontology engineer to validate.

### A schema mapping hypothesis answers:

> "How should data in field X of schema A be represented in field/path Y of schema B?"

**Example**:
```
source: Weight_g
target: measurements.bodyWeight.value
operation: nested_path
transformation:
  - copy numeric value
  - assign measurements.bodyWeight.unit = "g" (constant)
warning: "Weight_g has no associated measurement date; bodyWeight.date cannot be populated."
```

This is an **operational specification**. It can be wrong in an engineering sense. It requires a data engineer to validate.

---

## 4. Decision

Create a single monorepo with:

```
mapping_co_scientist/
  shared/          ← common process infrastructure
  ontology_align/  ← ontology mapping tool (CLI: ontology-align)
  schema_align/    ← schema mapping tool (CLI: schema-align)
```

**Key rules enforced by this decision:**

1. `schema_align` must **never** import from `ontology_align`.
2. `ontology_align` must **never** import from `schema_align`.
3. Both import **only** from `shared`.
4. `schema_align` exporters must **never** produce SSSOM output or SKOS predicates by default.
5. `ontology_align` agents must **never** produce operational transformation rules.
6. `MappingOperation` (schema) and `OntologyRelation` (ontology) are separate enumerations with no cross-import.

---

## 5. Backwards Compatibility

The original package `ontology_mapping_co_scientist` is preserved. Existing `omcs-run` and `omcs-review` CLI commands continue to work. New development targets `mapping_co_scientist.ontology_align` and `mapping_co_scientist.schema_align`.

---

## 6. Future Directions

- Both tools may share an LLM backend (same Anthropic SDK calls through `LLMProviderInterface`).
- A future unified UI (FastAPI or web) may present both tools under one interface while keeping their data models strictly separate.
- When a user explicitly requests RDF/JSON-LD output from `schema_align`, SSSOM export may be optionally enabled — but only as an explicit flag, not by default.

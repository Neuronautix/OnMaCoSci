# Evaluation Strategy

**Document**: `docs/evaluation_strategy.md`  
**Scope**: Separate evaluation benchmarks for `ontology-align` and `schema-align`

---

## Why Separate Benchmarks

The two tools answer different questions and have different failure modes. A unified "mapping accuracy" metric obscures both the distinct objectives and the specific error types that matter to each user community.

---

## 1. Ontology Alignment Metrics

### 1.1 Primary Accuracy Metrics

**Top-1 Alignment Accuracy**  
Definition: The fraction of source entities for which the highest-ranked candidate is the correct ontology term (as judged by expert reviewers).  
Target: ≥ 0.80 for lexical baseline; ≥ 0.90 for LLM-augmented  
Formula: `correct_top1 / total_source_entities`

**Top-3 Candidate Recall**  
Definition: The fraction of source entities for which the correct ontology term appears in the top-3 ranked candidates.  
Target: ≥ 0.92  
Formula: `entities_with_correct_in_top3 / total_source_entities`

**Relation/Predicate Accuracy**  
Definition: Among correctly identified target terms, the fraction for which the predicted SKOS predicate matches the expert-assigned predicate.  
Target: ≥ 0.75  
Predicates: exactMatch, closeMatch, broadMatch, narrowMatch, relatedMatch

**False exactMatch Rate**  
Definition: The fraction of proposed exactMatch mappings that are incorrect or over-claimed, as judged by an ontology engineer.  
Target: ≤ 0.05 (auto-generation of exactMatch is forbidden by design, so this should be 0.0 for the deterministic pipeline)  
Formula: `false_exactmatch_count / total_exactmatch_proposals`

### 1.2 Term Gap Detection Metrics

**Term Gap Detection Precision**  
Definition: Among proposed new ontology term proposals, the fraction judged by ontology engineers as genuinely needed.  
Target: ≥ 0.60 (lexical baseline), ≥ 0.80 (LLM-augmented)

**Term Gap Detection Recall**  
Definition: The fraction of truly missing ontology terms that the system identifies as gaps.  
Target: ≥ 0.70

### 1.3 Human Review Efficiency Metrics

**Expert Correction Time per Entity**  
Definition: Median time (minutes) for an ontology engineer to review, correct, and approve a mapping hypothesis.  
Baseline target: ≤ 3 minutes per entity for top-1 review  
Goal: System should reduce time compared to manual mapping from scratch (estimate: 15–30 min/entity without tool assistance)

**Adversarial Review Precision**  
Definition: Among high-severity adversarial flags, the fraction that represent genuine blocking issues (not false alarms).  
Target: ≥ 0.80  
Note: False alarms reduce reviewer trust; missed issues cause semantic errors.

### 1.4 Benchmark Dataset Requirements

- Minimum 50 source entities across ≥ 3 distinct source types (CSV, OpenAPI, JSON Schema)
- Target ontology with ≥ 100 terms, including terms with no suitable source match
- Expert-annotated ground truth with:
  - Correct target term per source entity (or `noSuitableMapping`)
  - Correct SKOS predicate
  - List of genuinely missing terms (gaps)
- At least 5 cases where the correct predicate is `narrowMatch` (not exactMatch)
- At least 3 cases where no suitable mapping exists

---

## 2. Schema Alignment Metrics

### 2.1 Primary Accuracy Metrics

**Correct Target Path Identification**  
Definition: The fraction of source fields for which the highest-confidence hypothesis identifies the correct target path.  
Target: ≥ 0.85 for flat-to-flat mappings; ≥ 0.75 for flat-to-nested mappings

**Transformation-Rule Accuracy**  
Definition: Among correctly identified field pairs, the fraction for which the inferred `MappingOperation` is correct.  
Operations: direct_copy, rename, nested_path, constant_assignment, datatype_conversion, unit_conversion  
Target: ≥ 0.80

**Datatype/Unit Conversion Accuracy**  
Definition: The fraction of hypotheses requiring datatype or unit conversion for which the conversion is correctly identified and the conversion factor is correct.  
Target: ≥ 0.90 for unit conversions (because errors here cause silent data corruption)

### 2.2 Robustness Metrics

**Information Loss Detection Rate**  
Definition: The fraction of truly lossy mappings (as judged by data engineers) that are flagged by the adversarial reviewer.  
Target: ≥ 0.85  
Note: False negatives here are more dangerous than false positives.

**Unmapped Field Detection Rate**  
Definition: The fraction of source fields with no suitable target that are correctly classified as `UNMAPPED` or `HUMAN_REVIEW_REQUIRED`.  
Target: ≥ 0.90

### 2.3 Transformation Quality Metrics

**Executable Transformation Test Pass Rate**  
Definition: Among generated transformation rules, the fraction that pass automated execution tests against example records.  
Target: ≥ 0.90 for `direct_copy`, `rename`, `constant_assignment` operations  
Note: `conditional`, `lookup`, `split` operations require manual test authoring.

**Round-Trip Fidelity**  
Definition: If a round-trip is possible (A→B→A), the fraction of values preserved exactly.  
Applicability: Only for bijective mappings (rename, direct_copy)  
Target: 1.00

### 2.4 Human Review Efficiency Metrics

**Human Correction Time per Field**  
Definition: Median time (minutes) for a data engineer to review, correct, and approve a field mapping hypothesis.  
Target: ≤ 2 minutes per field for top-1 review

**False Alarm Rate in Adversarial Review**  
Definition: The fraction of adversarial flags that are dismissed as non-issues by reviewers.  
Target: ≤ 0.20

### 2.5 Benchmark Dataset Requirements

- Minimum 30 source fields from ≥ 2 source types (CSV, JSON)
- Target schema with ≥ 40 fields, including nested paths (depth ≥ 3)
- Expert-annotated ground truth with:
  - Correct target path per source field (or `unmapped`)
  - Correct MappingOperation
  - Identified transformation requirements (datatype, unit, enumeration)
  - Information loss flags
- At least 3 constant-assignment cases (e.g. unit fields)
- At least 5 genuinely unmapped fields
- At least 2 cases of information loss (e.g. aggregation, missing date context)

---

## 3. Shared Evaluation Principles

1. **Confidence is not probability**: Reported confidence scores are ranking signals, not statistical likelihoods. Do not evaluate them as calibrated probabilities.

2. **Ground truth requires domain experts**: Neither automated metrics nor LLM judges replace ontology engineers (for ontology-align) or data engineers (for schema-align).

3. **Failure modes matter more than accuracy**: A 95% accuracy tool with a 5% silent exactMatch error rate is worse than a 85% accuracy tool with no silent errors.

4. **Measure human time, not just model quality**: The ultimate metric is "how much faster and more accurate is human review with the tool than without it?"

5. **Test on held-out domains**: Benchmark datasets must come from domains not used during development. Preclinical mouse metadata was the development domain; test on pharmacokinetics, biobanking, or clinical data.

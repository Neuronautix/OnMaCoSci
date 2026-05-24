# Ontology Alignment Review Report

**Pipeline Run**: example-oa-001
**Generated**: 2026-05-22T17:24:18.693994

**Total hypotheses**: 27
**Term gap proposals**: 0

---

## Mapping Candidates

### `csv:animal_id` → `AnimalIdentifier`

- **Relation**: `skos:closeMatch`
- **Confidence**: 1.00
- **Source type**: identifier
- **Target type**: annotation_property
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:Animal` (skos:closeMatch, conf=0.90)
- `hcm:HousingCage` (skos:closeMatch, conf=0.76)

---

### `csv:strain` → `MouseStrain`

- **Relation**: `skos:closeMatch`
- **Confidence**: 1.00
- **Source type**: attribute
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:HomeCageMonitoringDevice` (skos:broadMatch, conf=0.60)
- `hcm:ExperimentalGroup` (skos:relatedMatch, conf=0.54)

---

### `csv:sex` → `BiologicalSex`

- **Relation**: `skos:closeMatch`
- **Confidence**: 1.00
- **Source type**: attribute
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:Animal` (skos:broadMatch, conf=0.72)
- `hcm:ExperimentalGroup` (skos:broadMatch, conf=0.72)

---

### `csv:genotype` → `Genotype`

- **Relation**: `skos:closeMatch`
- **Confidence**: 1.00
- **Source type**: attribute
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:GeneticBackground` (skos:broadMatch, conf=0.60)
- `hcm:HousingCage` (skos:broadMatch, conf=0.60)

---

### `csv:cage_id` → `HousingCage`

- **Relation**: `skos:closeMatch`
- **Confidence**: 0.90
- **Source type**: identifier
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 0.90 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **identifier_to_class_mismatch**: Source is an identifier field but target is an ontology class. Identifiers typically map to annotation properties or data properties, not classes.
- [medium] **semantic_warning_lexical_only_high_score**: Score 0.90 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:HomeCageMonitoringDevice` (skos:closeMatch, conf=0.85)
- `hcm:GeneticBackground` (skos:relatedMatch, conf=0.54)

---

### `csv:body_weight` → `BodyWeightMeasurement`

- **Relation**: `skos:closeMatch`
- **Confidence**: 1.00
- **Source type**: measurement
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **measurement_to_class_mismatch**: Source appears to be a measurement/value but target is an ontology class. Consider whether target should be an object property or data property.
- [medium] **semantic_warning_lexical_only_high_score**: Score 1.00 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:Animal` (skos:relatedMatch, conf=0.47)
- `hcm:ExperimentalGroup` (skos:relatedMatch, conf=0.45)

---

### `csv:experimental_group` → `ExperimentalGroup`

- **Relation**: `skos:closeMatch`
- **Confidence**: 0.97
- **Source type**: field
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 0.97 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 0.97 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:BiologicalSex` (skos:broadMatch, conf=0.72)
- `hcm:Animal` (skos:broadMatch, conf=0.60)

---

### `csv:home_cage_monitoring_device` → `HomeCageMonitoringDevice`

- **Relation**: `skos:closeMatch`
- **Confidence**: 0.94
- **Source type**: field
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 0.94 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **semantic_warning_lexical_only_high_score**: Score 0.94 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:HousingCage` (skos:closeMatch, conf=0.90)
- `hcm:MouseStrain` (skos:broadMatch, conf=0.60)

---

### `csv:locomotor_activity_index` → `ActivityMeasurement`

- **Relation**: `skos:closeMatch`
- **Confidence**: 0.95
- **Source type**: measurement
- **Target type**: class
- **Validation**: passed

**Semantic Warnings:**
- [WARNING] Score 0.95 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Adversarial Review**: medium severity — review
- [medium] **measurement_to_class_mismatch**: Source appears to be a measurement/value but target is an ontology class. Consider whether target should be an object property or data property.
- [medium] **semantic_warning_lexical_only_high_score**: Score 0.95 is high enough for exactMatch by lexical metrics, but lexical similarity alone is insufficient to establish skos:exactMatch. Semantic review required before upgrading to exactMatch.

**Alternative candidates:**
- `hcm:BiologicalSex` (skos:broadMatch, conf=0.72)
- `hcm:ExperimentalGroup` (skos:broadMatch, conf=0.60)

---
